import logging
from collections import defaultdict
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
from reconcile.gql_definitions.endpoints_discovery.apps import (
    AppEndPointsV1,
    AppV1,
    NamespaceV1,
)
from reconcile.gql_definitions.endpoints_discovery.apps import (
    query as apps_query,
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
QONTRACT_INTEGRATION_VERSION = make_semver(1, 1, 0)


class EndpointsDiscoveryIntegrationParams(PydanticRunParams):
    thread_pool_size: int = 10
    internal: bool | None = None
    use_jump_host: bool = True
    cluster_name: set[str] | None = None
    app_name: str | None = None
    # To avoid the accidental deletion of the resource file, explicitly set the
    # qontract.cli option in the integration extraArgs!
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
    """Return the prefix for the endpoint name."""
    return f"{QONTRACT_INTEGRATION}/{namespace.cluster.name}/{namespace.name}/"


def parse_endpoint_name(endpoint_name: str) -> tuple[str, str, list[str]]:
    """Parse the endpoint name into its components."""
    integration_name, cluster, namespace, route_names = endpoint_name.split("/")
    if integration_name != QONTRACT_INTEGRATION:
        raise ValueError("Invalid integration name")
    return cluster, namespace, route_names.split("|")


def compile_endpoint_name(endpoint_prefix: str, route: Route) -> str:
    """Compile the endpoint name from the prefix and route."""
    return f"{endpoint_prefix}{route.name}"


def render_template(template: str, endpoint_name: str, route: Route) -> dict:
    """Render the endpoint yaml template used in the merge request."""
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
    apps: Iterable[AppV1]


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

    def get_apps(
        self,
        query_func: Callable,
        app_name: str | None = None,
    ) -> list[AppV1]:
        """Return all applications to consider for the integration."""
        return [
            app
            for app in apps_query(query_func).apps or []
            if (not app_name or app.name == app_name)
        ]

    def get_routes(self, oc_map: OCMap, namespace: NamespaceV1) -> list[Route]:
        """Return the routes for the given namespace."""
        oc = oc_map.get_cluster(namespace.cluster.name)
        if not oc.project_exists(namespace.name):
            logging.info(
                f"{namespace.cluster.name}/{namespace.name}: Namespace does not exist (yet). Skipping for now!"
            )
            return []

        routes = defaultdict(list)
        for item in oc.get_items(kind="Route", namespace=namespace.name):
            tls = bool(item["spec"].get("tls"))
            host = item["spec"]["host"]
            # group all routes with the same hostname/tls
            routes[host, tls].append(item["metadata"]["name"])

        # merge all routes with the same hostname into one and combine the names
        return [
            Route(
                name="|".join(sorted(names)),
                host=host,
                tls=tls,
            )
            for (host, tls), names in routes.items()
        ]

    def get_namespace_endpoint_changes(
        self,
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

        endpoints_to_add = [
            Endpoint(
                name=compile_endpoint_name(endpoint_prefix, add),
                data=render_template(
                    endpoint_template,
                    endpoint_name=compile_endpoint_name(endpoint_prefix, add),
                    route=add,
                ),
            )
            for add in diff.add.values()
        ]
        endpoints_to_change = [
            Endpoint(
                name=pair.current.name,
                data=render_template(
                    endpoint_template,
                    endpoint_name=compile_endpoint_name(endpoint_prefix, pair.desired),
                    route=pair.desired,
                ),
            )
            for pair in diff.change.values()
        ]
        endpoints_to_delete = [
            Endpoint(name=delete.name) for delete in diff.delete.values()
        ]
        return endpoints_to_add, endpoints_to_change, endpoints_to_delete

    def filter_ignored_routes(
        self, routes: list[Route], labels: dict[str, str]
    ) -> list[Route]:
        """Filter out the ignored routes."""
        return [
            route
            for route in routes
            if f"{QONTRACT_INTEGRATION}-{route.name}" not in labels
        ]

    def process(
        self,
        oc_map: OCMap,
        endpoint_template: str,
        apps: Iterable[AppV1],
        cluster_names: Iterable[str] | None = None,
    ) -> list[App]:
        """Compile a list of apps with their endpoints to add, change and delete."""
        apps_with_changes: list[App] = []
        for app in apps:
            app_endpoints = App(name=app.name, path=app.path)

            for namespace in app.namespaces or []:
                if not self.is_enabled(namespace, cluster_names=cluster_names):
                    continue

                logging.debug(
                    f"Processing namespace {namespace.cluster.name}/{namespace.name}"
                )

                routes = self.filter_ignored_routes(
                    self.get_routes(oc_map, namespace),
                    (app.labels or {}) | (namespace.labels or {}),
                )
                endpoints_to_add, endpoints_to_change, endpoints_to_delete = (
                    self.get_namespace_endpoint_changes(
                        endpoint_prefix=endpoint_prefix(namespace),
                        endpoint_template=endpoint_template,
                        endpoints=app.end_points or [],
                        routes=routes,
                    )
                )
                # update the app with the endpoints per namespace
                app_endpoints.endpoints_to_add += endpoints_to_add
                app_endpoints.endpoints_to_change += endpoints_to_change
                app_endpoints.endpoints_to_delete += endpoints_to_delete

            # remove endpoints from deleted namespaces
            namspace_names = {
                (ns.cluster.name, ns.name)
                for ns in app.namespaces or []
                if not ns.delete
            }
            for ep in app.end_points or []:
                try:
                    ep_cluster, ep_namespace, _ = parse_endpoint_name(ep.name)
                except ValueError:
                    continue
                if (ep_cluster, ep_namespace) not in namspace_names:
                    app_endpoints.endpoints_to_delete.append(Endpoint(name=ep.name))

            # log the changes
            for add in app_endpoints.endpoints_to_add:
                logging.info(f"{app.name}: Adding endpoint for route {add.name}")

            for change in app_endpoints.endpoints_to_change:
                logging.info(f"{app.name}: Changing endpoint for route {change.name}")

            for delete in app_endpoints.endpoints_to_delete:
                logging.info(f"{app.name}: Deleting endpoint for route {delete.name}")

            if (
                app_endpoints.endpoints_to_add
                or app_endpoints.endpoints_to_change
                or app_endpoints.endpoints_to_delete
            ):
                # ignore apps without changes
                apps_with_changes.append(app_endpoints)

        return apps_with_changes

    def runner(
        self,
        oc_map: OCMap,
        merge_request_manager: MergeRequestManager,
        endpoint_template: str,
        apps: Iterable[AppV1],
    ) -> ExtendedEarlyExitRunnerResult:
        """Reconcile the endpoints for all namespaces."""
        apps_with_changes = self.process(
            oc_map,
            endpoint_template,
            apps,
            cluster_names=self.params.cluster_name,
        )
        merge_request_manager.create_merge_request(apps=apps_with_changes)
        return ExtendedEarlyExitRunnerResult(
            payload={}, applied_count=len(apps_with_changes)
        )

    def is_enabled(
        self, namespace: NamespaceV1, cluster_names: Iterable[str] | None = None
    ) -> bool:
        """Check if the integration is enabled for the given namespace."""
        return (
            integration_is_enabled(self.name, namespace.cluster)
            and (not cluster_names or namespace.cluster.name in cluster_names)
            and not namespace.delete
        )

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        """Run the integration."""
        gql_api = gql.get_api()
        apps = self.get_apps(gql_api.query, app_name=self.params.app_name)
        if not apps:
            # nothing to do
            return

        oc_map = init_oc_map_from_namespaces(
            namespaces=[
                ns
                for app in apps
                for ns in app.namespaces or []
                if self.is_enabled(ns, self.params.cluster_name)
            ],
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
            "apps": apps,
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
