import logging
from collections.abc import Callable, Iterable
from typing import TypedDict

import jinja2
from pydantic import BaseModel

from reconcile.endpoints_discovery.merge_request import Renderer, create_parser
from reconcile.endpoints_discovery.merge_request_manager import (
    App,
    Endpoint,
    EndpointsToAdd,
    EndpointsToChange,
    EndpointsToDelete,
    MergeRequestManager,
)
from reconcile.gql_definitions.endpoints_discovery.namespaces import (
    AppEndPointsV1,
    NamespaceV1,
)
from reconcile.gql_definitions.endpoints_discovery.namespaces import (
    query as namespaces_query,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.differ import diff_any_iterables
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.extended_early_exit import (
    ExtendedEarlyExitRunnerResult,
    extended_early_exit_run,
)
from reconcile.utils.oc_map import OCMap, init_oc_map_from_namespaces
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "endpoints-discovery"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class EndpointsDiscoveryIntegrationParams(PydanticRunParams):
    thread_pool_size: int = 10
    internal: bool | None = None
    use_jump_host: bool = True
    cluster_name: set[str] | None = None
    namespace_name: str | None = None
    endpoint_tmpl_resource: str = "/endpoints-discovery/endpoint-template.yml"
    # extended early exit parameters
    enable_extended_early_exit: bool = False
    extended_early_exit_cache_ttl_seconds: int = 7200  # run every 2 hours
    log_cached_log_output: bool = False


class Route(BaseModel):
    name: str
    host: str
    tls: bool

    @property
    def url(self) -> str:
        return f"{self.host}:{443 if self.tls else 80}"


def endpoint_prefix(namespace: NamespaceV1) -> str:
    return f"{QONTRACT_INTEGRATION}/{namespace.cluster.name}/{namespace.name}/"


def compile_endpoint_name(endpoint_prefix: str, route: Route) -> str:
    return f"{endpoint_prefix}{route.name}"


def render_template(template: str, endpoint_name: str, route: Route) -> dict:
    yml = create_ruamel_instance()
    return yml.load(
        jinja2.Template(
            template,
            undefined=jinja2.StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        ).render({"endpoint_name": endpoint_name, "route": route})
    )


class RunnerParams(TypedDict):
    oc_map: OCMap
    merge_request_manager: MergeRequestManager
    endpoint_template: str
    namespaces: Iterable[NamespaceV1]


class EndpointsDiscoveryIntegration(
    QontractReconcileIntegration[EndpointsDiscoveryIntegrationParams]
):
    """Discover routes from all OpenShift clusters and update endPoints in app-interface."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_desired_state_shard_config(self) -> None:
        """Sharding (per cluster) is not supported for this integration.

        An application can have endpoints in multiple clusters and this may cause merge conflicts."""
        return None

    def get_namespaces(
        self,
        query_func: Callable,
        cluster_names: Iterable[str] | None = None,
        namespace_name: str | None = None,
    ) -> list[NamespaceV1]:
        """Return namespaces to consider for the integration."""
        return [
            ns
            for ns in namespaces_query(query_func).namespaces or []
            if integration_is_enabled(self.name, ns.cluster)
            and (not cluster_names or ns.cluster.name in cluster_names)
            and (not namespace_name or ns.name == namespace_name)
            and not ns.delete
        ]

    def get_routes(self, oc_map: OCMap, namespace: NamespaceV1) -> list[Route]:
        """Return the routes for the given namespace."""
        oc = oc_map.get_cluster(namespace.cluster.name)
        if not oc.project_exists(namespace.name):
            logging.info(
                f"{namespace.cluster.name}/{namespace.name}: Namespace does not exist (yet). Skipping for now!"
            )
            return []

        return [
            Route(
                name=item["metadata"]["name"],
                host=item["spec"]["host"],
                tls=bool(item["spec"].get("tls")),
            )
            for item in oc.get_items(kind="Route", namespace=namespace.name)
        ]

    def get_endpoint_changes(
        self,
        app: str,
        endpoint_prefix: str,
        endpoint_template: str,
        endpoints: Iterable[AppEndPointsV1],
        routes: Iterable[Route],
    ) -> tuple[EndpointsToAdd, EndpointsToChange, EndpointsToDelete]:
        """Get all new/changed/deleted endpoints for the given namespace."""
        if not routes and not endpoints:
            # nothing to do
            return [], [], []

        diff = diff_any_iterables(
            # exclude manual endpoints
            current=[
                endpoint
                for endpoint in endpoints
                if endpoint.name.startswith(endpoint_prefix)
            ]
            or [],
            desired=routes,
            # names are unique, so we can use them as keys
            current_key=lambda endpoint: endpoint.name,
            desired_key=lambda route: compile_endpoint_name(endpoint_prefix, route),
            # compare the endpoint and route by url.
            # we can't use other endpoint attributes because we don't want to query them.
            # there is a note about that behavior in the template.
            equal=lambda endpoint, route: endpoint.url == route.url,
        )

        endpoints_to_add = []
        endpoints_to_change = []
        endpoints_to_delete = []

        for add in diff.add.values():
            logging.info(f"{app}: Adding endpoint for route {add.name}")
            endpoints_to_add.append(
                Endpoint(
                    name=compile_endpoint_name(endpoint_prefix, add),
                    data=render_template(
                        endpoint_template,
                        endpoint_name=compile_endpoint_name(endpoint_prefix, add),
                        route=add,
                    ),
                )
            )

        for pair in diff.change.values():
            logging.info(
                f"{app}: Changing endpoint {pair.current.name} for route {pair.desired.name}"
            )
            endpoints_to_change.append(
                Endpoint(
                    name=pair.current.name,
                    data=render_template(
                        endpoint_template,
                        endpoint_name=compile_endpoint_name(
                            endpoint_prefix, pair.desired
                        ),
                        route=pair.desired,
                    ),
                )
            )
        for delete in diff.delete.values():
            logging.info(f"{app}: Deleting endpoint for route {delete.name}")
            endpoints_to_delete.append(Endpoint(name=delete.name))
        return endpoints_to_add, endpoints_to_change, endpoints_to_delete

    def get_apps(
        self, oc_map: OCMap, endpoint_template: str, namespaces: Iterable[NamespaceV1]
    ) -> list[App]:
        """Compile a list of apps with their endpoints to add, change and delete."""
        apps: dict[str, App] = {}
        for namespace in namespaces:
            logging.debug(
                f"Processing namespace {namespace.cluster.name}/{namespace.name}"
            )
            routes = self.get_routes(oc_map, namespace)
            endpoints_to_add, endpoints_to_change, endpoints_to_delete = (
                self.get_endpoint_changes(
                    app=namespace.app.name,
                    endpoint_prefix=endpoint_prefix(namespace),
                    endpoint_template=endpoint_template,
                    endpoints=namespace.app.end_points or [],
                    routes=routes,
                )
            )
            # update the app with the endpoints per namespace
            app = apps.setdefault(
                namespace.app.path,
                App(name=namespace.app.name, path=namespace.app.path),
            )
            app.endpoints_to_add += endpoints_to_add
            app.endpoints_to_change += endpoints_to_change
            app.endpoints_to_delete += endpoints_to_delete

        # return only apps endpoint changes
        return [
            app
            for app in apps.values()
            if app.endpoints_to_add
            or app.endpoints_to_change
            or app.endpoints_to_delete
        ]

    def runner(
        self,
        oc_map: OCMap,
        merge_request_manager: MergeRequestManager,
        endpoint_template: str,
        namespaces: Iterable[NamespaceV1],
    ) -> ExtendedEarlyExitRunnerResult:
        """Reconcile the endpoints for all namespaces."""
        apps = self.get_apps(oc_map, endpoint_template, namespaces)
        merge_request_manager.create_merge_request(apps=apps)
        return ExtendedEarlyExitRunnerResult(payload={}, applied_count=len(apps))

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        namespaces = self.get_namespaces(
            gql_api.query,
            cluster_names=self.params.cluster_name,
            namespace_name=self.params.namespace_name,
        )
        if not namespaces:
            # nothing to do
            return

        oc_map = init_oc_map_from_namespaces(
            namespaces=namespaces,
            secret_reader=self.secret_reader,
            integration=QONTRACT_INTEGRATION,
            use_jump_host=self.params.use_jump_host,
            thread_pool_size=self.params.thread_pool_size,
            internal=self.params.internal,
            init_projects=True,
        )

        if defer:
            defer(oc_map.cleanup)

        vcs = VCS(
            secret_reader=self.secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
            allow_deleting_mrs=True,
            allow_opening_mrs=True,
        )
        if defer:
            defer(vcs.cleanup)
        merge_request_manager = MergeRequestManager(
            vcs=vcs,
            renderer=Renderer(),
            parser=create_parser(),
            auto_merge_enabled=get_feature_toggle_state(
                integration_name=f"{self.name}-allow-auto-merge-mrs", default=False
            ),
        )
        endpoint_template = gql_api.get_resource(
            path=self.params.endpoint_tmpl_resource
        )["content"]

        runner_params: RunnerParams = {
            "oc_map": oc_map,
            "merge_request_manager": merge_request_manager,
            "endpoint_template": endpoint_template,
            "namespaces": namespaces,
        }

        if self.params.enable_extended_early_exit and get_feature_toggle_state(
            f"{QONTRACT_INTEGRATION}-extended-early-exit", default=True
        ):
            extended_early_exit_run(
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
                dry_run=dry_run,
                cache_source=self.get_early_exit_desired_state(),
                shard="",
                ttl_seconds=self.params.extended_early_exit_cache_ttl_seconds,
                logger=logging.getLogger(),
                runner=self.runner,
                runner_params=runner_params,
                log_cached_log_output=self.params.log_cached_log_output,
            )
        else:
            self.runner(**runner_params)
