"""OpenShift namespaces reconciliation service.

Layer 3 (Business Logic) following ADR-014. Pure business logic only —
no Layer 1 imports, no secret reading, no client creation.
Implements plan-and-apply pattern: builds the complete diff first,
then executes (dry_run checked only at execution).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_api.integrations.openshift_namespaces.schemas import (
    CreateNamespaceAction,
    DeleteNamespaceAction,
    OpenShiftNamespacesTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

if TYPE_CHECKING:
    from qontract_api.integrations.openshift_namespaces.domain import (
        DesiredNamespace,
    )
    from qontract_api.kubernetes.workspace_client import KubernetesWorkspaceClient

logger = get_logger(__name__)

_AnyAction = CreateNamespaceAction | DeleteNamespaceAction


class OpenShiftNamespacesService:
    """Reconciles Kubernetes namespaces across clusters.

    Plan-and-Apply: calculates the complete diff first, then executes.
    dry_run is only checked at the execution point.

    Receives ready-to-use workspace clients — does NOT create clients,
    read secrets, or import Layer 1 modules.
    """

    def reconcile(
        self,
        cluster_clients: dict[str, KubernetesWorkspaceClient],
        cluster_namespaces: dict[str, list[DesiredNamespace]],
        *,
        dry_run: bool = True,
    ) -> OpenShiftNamespacesTaskResult:
        """Reconcile namespaces across clusters.

        Args:
            cluster_clients: Workspace clients keyed by cluster name.
            cluster_namespaces: Desired namespaces keyed by cluster name.
            dry_run: If True, only calculate actions without executing.

        Returns:
            Task result with all planned and applied actions.
        """
        all_actions: list[_AnyAction] = []
        applied_actions: list[_AnyAction] = []
        errors: list[str] = []

        for cluster_name, namespaces in cluster_namespaces.items():
            ws_client = cluster_clients.get(cluster_name)
            if not ws_client:
                errors.append(f"No client for cluster {cluster_name!r}")
                continue
            try:
                actions = self._calculate_cluster_actions(
                    cluster_name, namespaces, ws_client
                )
                all_actions.extend(actions)
            except Exception as e:
                error_msg = f"Failed to process cluster {cluster_name}: {e}"
                logger.exception(error_msg)
                errors.append(error_msg)

        if not dry_run:
            for action in all_actions:
                try:
                    self._execute_action(action, cluster_clients)
                    applied_actions.append(action)
                except Exception as e:
                    error_msg = f"Failed to execute {action.action_type} on {action.cluster}/{action.namespace}: {e}"
                    logger.exception(error_msg)
                    errors.append(error_msg)

        return OpenShiftNamespacesTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )

    @staticmethod
    def _calculate_cluster_actions(
        cluster_name: str,
        namespaces: list[DesiredNamespace],
        ws_client: KubernetesWorkspaceClient,
    ) -> list[_AnyAction]:
        actions: list[_AnyAction] = []
        for ns in namespaces:
            exists = ws_client.namespace_exists(ns.name)
            match (ns.delete, exists):
                case (False, False):
                    actions.append(
                        CreateNamespaceAction(cluster=cluster_name, namespace=ns.name)
                    )
                case (True, True):
                    actions.append(
                        DeleteNamespaceAction(cluster=cluster_name, namespace=ns.name)
                    )
        return actions

    @staticmethod
    def _execute_action(
        action: _AnyAction,
        workspace_clients: dict[str, KubernetesWorkspaceClient],
    ) -> None:
        ws_client = workspace_clients[action.cluster]
        match action:
            case CreateNamespaceAction():
                ws_client.create_namespace(action.namespace)
            case DeleteNamespaceAction():
                ws_client.delete_namespace(action.namespace)
