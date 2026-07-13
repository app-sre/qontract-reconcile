"""Celery tasks for openshift-namespaces reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.openshift_namespaces.schemas import (
    OpenShiftNamespacesTaskResult,
)
from qontract_api.integrations.openshift_namespaces.service import (
    OpenShiftNamespacesService,
)
from qontract_api.kubernetes.cluster_client_map import (
    ClusterClientMap,
    ClusterConnectionParams,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.openshift_namespaces.domain import (
        ClusterNamespaces,
        DesiredNamespace,
    )
    from qontract_api.secret_manager._base import SecretManager

logger = get_logger(__name__)


def _resolve_cluster_connection(
    cluster: ClusterNamespaces,
    secret_manager: SecretManager,
) -> ClusterConnectionParams:
    """Resolve cluster connection params by reading the automation token."""
    return ClusterConnectionParams(
        cluster_name=cluster.cluster_name,
        server=cluster.server_url,
        token=secret_manager.read(cluster.automation_token),
        insecure_skip_tls_verify=cluster.insecure_skip_tls_verify,
    )


def _publish_result_events(
    result: OpenShiftNamespacesTaskResult,
    *,
    dry_run: bool,
) -> None:
    """Publish CloudEvents for applied actions and errors."""
    if dry_run:
        return
    event_manager = get_event_manager()
    if not event_manager:
        return

    for action in result.applied_actions:
        event_manager.publish_event(
            Event(
                source=__name__,
                type=f"qontract-api.openshift-namespaces.{action.action_type}",
                data=action.model_dump(mode="json"),
                datacontenttype="application/json",
            )
        )
    for error in result.errors:
        event_manager.publish_event(
            Event(
                source=__name__,
                type="qontract-api.openshift-namespaces.error",
                data={"error": error},
                datacontenttype="application/json",
            )
        )


def generate_lock_key(_self: Task, clusters: list[ClusterNamespaces], **_: Any) -> str:
    """Generate deduplication lock key based on cluster names."""
    cluster_names = sorted(c.cluster_name for c in clusters)
    return ",".join(cluster_names)


@celery_app.task(bind=True, name="openshift_namespaces.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_openshift_namespaces_task(
    self: Any,
    clusters: list[ClusterNamespaces],
    *,
    dry_run: bool = True,
) -> OpenShiftNamespacesTaskResult:
    """Reconcile openshift namespaces (background task)."""
    request_id = self.request.id
    secret_errors: list[str] = []

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)

        connection_params: list[ClusterConnectionParams] = []
        for cluster in clusters:
            try:
                params = _resolve_cluster_connection(cluster, secret_manager)
            except Exception:
                error_msg = f"Failed to read token for cluster {cluster.cluster_name}"
                logger.exception(error_msg)
                secret_errors.append(error_msg)
            else:
                connection_params.append(params)

        connected_clusters = {p.cluster_name for p in connection_params}
        cluster_namespaces: dict[str, list[DesiredNamespace]] = {
            cluster.cluster_name: list(cluster.namespaces)
            for cluster in clusters
            if cluster.cluster_name in connected_clusters
        }

        if not connection_params:
            result = OpenShiftNamespacesTaskResult(
                status=TaskStatus.FAILED,
                actions=[],
                applied_count=0,
                errors=secret_errors,
            )
            _publish_result_events(result, dry_run=dry_run)
            return result

        with ClusterClientMap(connection_params, cache, settings) as cluster_map:
            service = OpenShiftNamespacesService()
            result = service.reconcile(
                cluster_clients=dict(cluster_map.items()),
                cluster_namespaces=cluster_namespaces,
                dry_run=dry_run,
            )

        if secret_errors:
            result = OpenShiftNamespacesTaskResult(
                status=TaskStatus.FAILED,
                actions=result.actions,
                applied_actions=result.applied_actions,
                applied_count=result.applied_count,
                errors=[*secret_errors, *result.errors],
            )

        logger.info(
            f"Task {request_id} completed",
            status=result.status,
            total_actions=len(result.actions),
            applied_count=result.applied_count,
            actions=[action.model_dump() for action in result.actions],
            errors=result.errors,
        )

        _publish_result_events(result, dry_run=dry_run)
        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        result = OpenShiftNamespacesTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[*secret_errors, str(e)],
        )
        _publish_result_events(result, dry_run=dry_run)
        return result
