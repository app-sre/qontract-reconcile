"""OpenShift namespaces reconciliation via qontract-api."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from qontract_api_client.client import (
    openshift_namespaces as openshift_namespaces_reconcile,
)
from qontract_api_client.schemas import (
    ClusterNamespaces,
    DesiredNamespace,
    OpenShiftNamespacesReconcileRequest,
    OpenShiftNamespacesTaskResponse,
    OpenShiftNamespacesTaskResult,
    Secret,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError

from reconcile.typed_queries.namespaces_minimal import get_namespaces_minimal
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from reconcile.gql_definitions.common.namespaces_minimal import NamespaceV1

QONTRACT_INTEGRATION = "openshift-namespaces-api"
QONTRACT_INTEGRATION_UPSTREAM = "openshift-namespaces"


class OpenShiftNamespacesIntegrationParams(PydanticRunParams):
    """Parameters for openshift-namespaces-api integration."""

    cluster_name: str | None = None
    namespace_name: str | None = None


class OpenShiftNamespacesIntegration(
    QontractReconcileApiIntegration[OpenShiftNamespacesIntegrationParams]
):
    """Manage OpenShift namespaces via qontract-api.

    1. Queries App-Interface for namespace definitions
    2. Filters by cluster/namespace name if specified
    3. Compiles desired state per cluster (with Secret references)
    4. Sends to qontract-api for reconciliation
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def compile_desired_state(
        self,
        namespaces: list[NamespaceV1],
    ) -> list[ClusterNamespaces]:
        """Compile namespace definitions into per-cluster desired state.

        Args:
            namespaces: Namespace definitions from GraphQL

        Returns:
            List of ClusterNamespaces with Secret references (no actual tokens)
        """
        by_cluster: dict[str, list[DesiredNamespace]] = defaultdict(list)
        cluster_info: dict[str, NamespaceV1] = {}

        for ns in namespaces:
            cluster_name = ns.cluster.name
            by_cluster[cluster_name].append(
                DesiredNamespace(name=ns.name, delete=ns.delete or False)
            )
            if cluster_name not in cluster_info:
                cluster_info[cluster_name] = ns

        result: list[ClusterNamespaces] = []
        for cluster_name, desired_namespaces in by_cluster.items():
            ns_ref = cluster_info[cluster_name]
            token_ref = ns_ref.cluster.automation_token
            if not token_ref:
                logging.warning(
                    f"No automation token for cluster '{cluster_name}' — skipping"
                )
                continue

            result.append(
                ClusterNamespaces(
                    cluster_name=cluster_name,
                    server_url=ns_ref.cluster.server_url,
                    automation_token=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=token_ref.path,
                        field=token_ref.field,
                        version=token_ref.version,
                    ),
                    namespaces=desired_namespaces,
                )
            )

        return result

    async def reconcile(
        self,
        clusters: list[ClusterNamespaces],
        dry_run: bool,
    ) -> OpenShiftNamespacesTaskResponse:
        """Send desired state to qontract-api."""
        request = OpenShiftNamespacesReconcileRequest(
            clusters=clusters,
            dry_run=dry_run,
        )
        response = await openshift_namespaces_reconcile(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        all_namespaces = get_namespaces_minimal()
        filtered = self._apply_filters(all_namespaces)
        clusters = self.compile_desired_state(filtered)

        if not clusters:
            logging.warning("No desired state found, nothing to reconcile")
            return

        task = await self.reconcile(clusters=clusters, dry_run=dry_run)

        if not dry_run:
            return

        task_result = await self.poll_task_status(
            status_url=task.status_url,
            result_type=OpenShiftNamespacesTaskResult,
        )
        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                "openshift-namespaces-api: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            logging.info(f"{action.action_type=} {action.cluster=} {action.namespace=}")

        if task_result.errors:
            errors_summary = "; ".join(task_result.errors)
            raise IntegrationError(
                f"openshift-namespaces-api: {len(task_result.errors)} error(s): {errors_summary}"
            )

    def _apply_filters(self, namespaces: list[NamespaceV1]) -> list[NamespaceV1]:
        """Apply cluster and namespace name filters."""
        result = [
            ns
            for ns in namespaces
            if integration_is_enabled(QONTRACT_INTEGRATION, ns.cluster)
            and integration_is_enabled(QONTRACT_INTEGRATION_UPSTREAM, ns.cluster)
        ]
        if self.params.cluster_name:
            result = [
                ns for ns in result if ns.cluster.name == self.params.cluster_name
            ]
        if self.params.namespace_name:
            result = [ns for ns in result if ns.name == self.params.namespace_name]
        return result
