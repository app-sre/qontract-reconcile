"""Endpoints discovery via qontract-api.

Client-side integration that compiles desired state from App-Interface and
delegates route discovery, YAML merging and merge request management to
qontract-api.

See ADR-002 (client-side GraphQL), ADR-008 (integration naming) and ADR-013
(external API calls go through qontract-api).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qontract_api_client.client import endpoints_discovery
from qontract_api_client.schemas import (
    AddEndpointAction,
    AppInterfaceRepo,
    ChangeEndpointAction,
    ClusterConnection,
    CurrentEndpoint,
    DeleteEndpointAction,
    DesiredApp,
    EndpointsDiscoveryReconcileRequest,
    EndpointsDiscoveryTaskResponse,
    EndpointsDiscoveryTaskResult,
    NamespaceDesiredState,
    Secret,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.endpoints_discovery_api.apps import AppV1, NamespaceV1
from reconcile.gql_definitions.endpoints_discovery_api.apps import (
    query as apps_query,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.vcs import get_vcs_instances
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)
from reconcile.utils.unleash import get_feature_toggle_state

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from reconcile.gql_definitions.fragments.oc_connection_cluster import (
        AutomationTokenEntryV1,
        OcConnectionCluster,
    )
    from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
    from reconcile.typed_queries.vcs import Vcs

QONTRACT_INTEGRATION = "endpoints-discovery-api"
# The legacy name gates cluster disablement and the auto-merge toggle, so both
# keep working across the rollout without operator changes.
QONTRACT_INTEGRATION_UPSTREAM = "endpoints-discovery"

AUTO_MERGE_TOGGLE = f"{QONTRACT_INTEGRATION_UPSTREAM}-allow-auto-merge-mrs"
DEFAULT_TEMPLATE_RESOURCE = "/endpoints-discovery/endpoint-template.yml"


def _active_token_secret(
    entries: Iterable[AutomationTokenEntryV1] | None,
) -> VaultSecret | None:
    """Return the first active, non-deleted list token that has a secret."""
    for entry in entries or []:
        if entry.active and not entry.delete and entry.secret is not None:
            return entry.secret
    return None


def _cluster_token(cluster: OcConnectionCluster) -> VaultSecret | None:
    """Prefer the rotation-aware token list, falling back to the legacy field."""
    return _active_token_secret(cluster.automation_tokens) or cluster.automation_token


def _find_vcs_secret(
    secret_manager_url: str, vcs_instances: Iterable[Vcs], repo_url: str
) -> Secret:
    """Find the token reference for a repository from the configured VCS instances."""
    for vcs in vcs_instances:
        if repo_url.startswith(vcs.url):
            return Secret(
                secret_manager_url=secret_manager_url,
                path=vcs.token.path,
                field=vcs.token.field,
                version=vcs.token.version,
            )
    raise IntegrationError(
        f"{QONTRACT_INTEGRATION}: no VCS instance found for repo URL {repo_url}"
    )


class EndpointsDiscoveryApiIntegrationParams(PydanticRunParams):
    """Parameters for the endpoints-discovery-api integration."""

    app_name: str | None = None
    cluster_name: set[str] | None = None
    internal: bool | None = None
    # To avoid the accidental deletion of the resource file, the qontract.cli
    # option must be set explicitly in the integration extraArgs.
    endpoint_tmpl_resource: str = DEFAULT_TEMPLATE_RESOURCE


class EndpointsDiscoveryApiIntegration(
    QontractReconcileApiIntegration[EndpointsDiscoveryApiIntegrationParams]
):
    """Discover routes and update application endpoints via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_apps(self, query_func: Callable) -> list[AppV1]:
        """Return all applications to consider for the integration."""
        return list(apps_query(query_func=query_func).apps or [])

    def compile_desired_state(
        self,
        apps: Iterable[AppV1],
        *,
        cluster_names: set[str] | None,
        internal: bool | None,
    ) -> list[DesiredApp]:
        """Compile the request payload from App-Interface apps.

        Every non-deleted namespace is sent, even when filtered or disabled,
        with `discover=False`. The server needs the full set to decide that
        those endpoints still exist, and only connects to clusters that have
        a namespace to discover.
        """
        desired: list[DesiredApp] = []
        errors: list[str] = []

        for app in apps:
            if self.params.app_name and app.name != self.params.app_name:
                continue

            namespaces: list[NamespaceDesiredState] = []
            for namespace in app.namespaces or []:
                cluster = namespace.cluster
                discover = self._is_discoverable(
                    cluster, namespace, cluster_names, internal
                )
                token = _cluster_token(cluster)
                if discover and token is None:
                    errors.append(
                        f"{cluster.name}/{namespace.name}: no automationToken "
                        "(cannot discover routes)"
                    )
                    continue

                namespaces.append(
                    NamespaceDesiredState(
                        name=namespace.name,
                        labels=dict(namespace.labels or {}),
                        delete=bool(namespace.delete),
                        discover=discover,
                        cluster=ClusterConnection(
                            cluster_name=cluster.name,
                            server_url=cluster.server_url,
                            automation_token=self._secret_for(token),
                            insecure_skip_tls_verify=bool(
                                cluster.insecure_skip_tls_verify
                            ),
                            internal=cluster.internal,
                            disabled_integrations=list(
                                cluster.disable.integrations or []
                            )
                            if cluster.disable
                            else [],
                        ),
                    )
                )

            desired.append(
                DesiredApp(
                    name=app.name,
                    path=app.path,
                    labels=dict(app.labels or {}),
                    end_points=[
                        CurrentEndpoint(name=endpoint.name, url=endpoint.url)
                        for endpoint in app.end_points or []
                    ],
                    namespaces=namespaces,
                )
            )

        if errors:
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: {len(errors)} error(s): {'; '.join(errors)}"
            )
        return desired

    def compile_app_interface_repo(
        self, repo_url: str, vcs_instances: Iterable[Vcs]
    ) -> AppInterfaceRepo:
        """Build the repository config with the matching token reference."""
        return AppInterfaceRepo(
            repo_url=repo_url,
            token=_find_vcs_secret(self.secret_manager_url, vcs_instances, repo_url),
            target_branch="master",
        )

    @staticmethod
    def build_request(
        *,
        apps: list[DesiredApp],
        endpoint_template: str,
        app_interface: AppInterfaceRepo,
        auto_merge: bool,
        dry_run: bool,
    ) -> EndpointsDiscoveryReconcileRequest:
        """Build the reconciliation request."""
        return EndpointsDiscoveryReconcileRequest(
            apps=apps,
            endpoint_template=endpoint_template,
            app_interface=app_interface,
            auto_merge=auto_merge,
            dry_run=dry_run,
        )

    async def reconcile(
        self,
        request: EndpointsDiscoveryReconcileRequest,
    ) -> EndpointsDiscoveryTaskResponse:
        """Send desired state to qontract-api and return the task response."""
        with self.log_api_exceptions():
            response = await endpoints_discovery(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gqlapi = gql.get_api()
        apps = self.get_apps(gqlapi.query)
        if not apps:
            logging.debug("No apps found, nothing to reconcile")
            return

        desired_apps = self.compile_desired_state(
            apps,
            cluster_names=self.params.cluster_name,
            internal=self.params.internal,
        )
        if not desired_apps:
            logging.debug("No apps selected, nothing to reconcile")
            return

        request = self.build_request(
            apps=desired_apps,
            endpoint_template=gqlapi.get_resource(
                path=self.params.endpoint_tmpl_resource
            )["content"],
            app_interface=self.compile_app_interface_repo(
                get_app_interface_repo_url(), get_vcs_instances()
            ),
            auto_merge=get_feature_toggle_state(AUTO_MERGE_TOGGLE, default=False),
            dry_run=dry_run,
        )

        task = await self.reconcile(request)
        if not dry_run:
            return

        result = await self.poll_task_status(
            status_url=task.status_url,
            result_type=EndpointsDiscoveryTaskResult,
        )
        if result.status == TaskStatus.PENDING:
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: task did not complete within the "
                "timeout period"
            )

        for action in result.actions:
            match action:
                case AddEndpointAction():
                    logging.info(
                        f"{action.app_name}: add endpoint {action.endpoint_name} "
                        f"({action.cluster}/{action.namespace})"
                    )
                case ChangeEndpointAction():
                    logging.info(
                        f"{action.app_name}: change endpoint {action.endpoint_name} "
                        f"({action.cluster}/{action.namespace})"
                    )
                case DeleteEndpointAction():
                    logging.info(
                        f"{action.app_name}: delete endpoint {action.endpoint_name}"
                    )

        if result.errors:
            raise IntegrationError(
                f"{QONTRACT_INTEGRATION}: {len(result.errors)} error(s): "
                f"{'; '.join(result.errors)}"
            )

    def _is_discoverable(
        self,
        cluster: OcConnectionCluster,
        namespace: NamespaceV1,
        cluster_names: set[str] | None,
        internal: bool | None,
    ) -> bool:
        """Decide whether the server should read this namespace's routes.

        Both names are checked so a cluster disabled during rollout is not
        silently processed by the new integration.
        """
        if namespace.delete:
            return False
        if cluster_names and cluster.name not in cluster_names:
            return False
        if internal is not None and bool(cluster.internal) != internal:
            return False
        return integration_is_enabled(
            QONTRACT_INTEGRATION, cluster
        ) and integration_is_enabled(QONTRACT_INTEGRATION_UPSTREAM, cluster)

    def _secret_for(self, token: VaultSecret | None) -> Secret | None:
        if token is None:
            return None
        return Secret(
            secret_manager_url=self.secret_manager_url,
            path=token.path,
            field=token.field,
            version=token.version,
        )
