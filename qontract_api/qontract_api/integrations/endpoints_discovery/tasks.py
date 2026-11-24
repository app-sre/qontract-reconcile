"""Celery tasks for endpoints-discovery reconciliation.

The task is the composition root: it resolves Vault references, builds the
Layer 2 clients, and hands them to the Layer 3 service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.endpoints_discovery.schemas import (
    EndpointsDiscoveryReconcileRequest,
    EndpointsDiscoveryTaskResult,
)
from qontract_api.integrations.endpoints_discovery.service import (
    EndpointsDiscoveryService,
)
from qontract_api.kubernetes.cluster_client_map import (
    ClusterClientMap,
    ClusterConnectionParams,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task
from qontract_api.vcs.vcs_factory import create_vcs_workspace_client

if TYPE_CHECKING:
    from collections.abc import Iterable

    from celery import Task

    from qontract_api.event_manager import EventManager
    from qontract_api.integrations.endpoints_discovery.domain import (
        ClusterConnection,
        DesiredApp,
    )
    from qontract_api.secret_manager._base import SecretManager

logger = get_logger(__name__)

_TASK_LOCK_TIMEOUT_SECONDS = 600


def generate_lock_key(
    _self: Task,
    # The payload is ignored on purpose. The name is kept as `request` because
    # the deduplication wrapper forwards task keyword arguments by name.
    request: EndpointsDiscoveryReconcileRequest,  # ruff: ignore[unused-function-argument]
    **_: Any,
) -> str:
    """Return a constant lock key.

    The integration keeps at most one merge request for every application, so
    two live runs must never overlap regardless of which apps they carry.
    """
    return "endpoints-discovery"


def _unique_clusters(apps: Iterable[DesiredApp]) -> dict[str, ClusterConnection]:
    """Collect one connection per cluster that has a namespace to discover.

    Filtered and deleted namespaces are still in the payload so their
    endpoints are preserved, but they need no cluster connection.
    """
    clusters: dict[str, ClusterConnection] = {}
    for app in apps:
        for namespace in app.namespaces:
            if not namespace.discover:
                continue
            clusters.setdefault(namespace.cluster.cluster_name, namespace.cluster)
    return clusters


def _resolve_cluster_connection(
    cluster: ClusterConnection, secret_manager: SecretManager
) -> ClusterConnectionParams:
    """Resolve a cluster automation token, validating it belongs to the cluster."""
    secret = cluster.automation_token
    if secret is None:
        raise ValueError("cluster has no automationToken")
    secret_data = secret_manager.read_all(secret)
    secret_server = secret_data.get("server")
    if secret_server != cluster.server_url:
        raise ValueError(
            f"token secret server {secret_server!r} does not match cluster "
            f"serverUrl {cluster.server_url!r}"
        )
    field = secret.field
    if not field:
        raise ValueError("automation token secret has no field")
    return ClusterConnectionParams(
        cluster_name=cluster.cluster_name,
        server=cluster.server_url,
        token=secret_data[field],
        insecure_skip_tls_verify=cluster.insecure_skip_tls_verify,
    )


def _resolve_cluster_connections(
    apps: Iterable[DesiredApp], secret_manager: SecretManager
) -> tuple[list[ClusterConnectionParams], list[str]]:
    """Resolve every cluster token, isolating per-cluster failures."""
    connection_params: list[ClusterConnectionParams] = []
    errors: list[str] = []
    for cluster_name, cluster in _unique_clusters(apps).items():
        try:
            connection_params.append(
                _resolve_cluster_connection(cluster, secret_manager)
            )
        except Exception as e:
            error_msg = f"Failed to read token for cluster {cluster_name}: {e}"
            logger.exception(error_msg)
            errors.append(error_msg)
    return connection_params, errors


def _publish_result_events(
    result: EndpointsDiscoveryTaskResult,
    *,
    dry_run: bool,
    request_id: str,
) -> None:
    """Publish CloudEvents for applied actions, the MR outcome and errors."""
    if dry_run:
        return

    try:
        event_manager = get_event_manager()
        if event_manager:
            _publish_events(event_manager, result)
    except Exception:
        logger.exception(f"Task {request_id} failed to publish events")


def _publish_events(
    event_manager: EventManager, result: EndpointsDiscoveryTaskResult
) -> None:
    """Publish the individual events for one completed result."""
    for action in result.applied_actions:
        event_manager.publish_event(
            Event(
                source=__name__,
                type=f"qontract-api.endpoints-discovery.{action.action_type}",
                data=action.model_dump(mode="json"),
                datacontenttype="application/json",
            )
        )
    if result.mr_status is not None:
        event_manager.publish_event(
            Event(
                source=__name__,
                type="qontract-api.endpoints-discovery.merge-request",
                data={
                    "status": result.mr_status.value,
                    "mr_url": result.mr_url,
                    "apps_with_changes": result.apps_with_changes,
                    "actions_count": len(result.actions),
                },
                datacontenttype="application/json",
            )
        )
    for error in result.errors:
        event_manager.publish_event(
            Event(
                source=__name__,
                type="qontract-api.endpoints-discovery.error",
                data={"error": error},
                datacontenttype="application/json",
            )
        )


@celery_app.task(bind=True, name="endpoints-discovery.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=_TASK_LOCK_TIMEOUT_SECONDS)
def reconcile_endpoints_discovery_task(
    self: Any,
    request: EndpointsDiscoveryReconcileRequest,
    *,
    dry_run: bool = True,
) -> EndpointsDiscoveryTaskResult:
    """Reconcile application endpoints from live routes (background task)."""
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return EndpointsDiscoveryTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected {err=}"],
        )

    connection_params, secret_errors = _resolve_cluster_connections(
        request.apps, secret_manager
    )

    vcs_token: str | None = None
    try:
        vcs_token = secret_manager.read(request.app_interface.token)
    except Exception as err:
        error_msg = f"Failed to read App-Interface repository token: {err}"
        logger.exception(error_msg)
        secret_errors.append(error_msg)

    has_discoverable_namespaces = any(
        namespace.discover for app in request.apps for namespace in app.namespaces
    )
    if vcs_token is None or (has_discoverable_namespaces and not connection_params):
        result = EndpointsDiscoveryTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=secret_errors,
        )
        _publish_result_events(result, dry_run=dry_run, request_id=request_id)
        return result

    try:
        vcs_client = create_vcs_workspace_client(
            repo_url=request.app_interface.repo_url,
            token=vcs_token,
            cache=cache,
            settings=settings,
        )
        with ClusterClientMap(connection_params, cache, settings) as cluster_map:
            service = EndpointsDiscoveryService(
                cluster_clients=dict(cluster_map.items()),
                vcs_client=vcs_client,
            )
            result = service.reconcile(request, dry_run=dry_run)
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        result = EndpointsDiscoveryTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[*secret_errors, f"Unexpected {err=}"],
        )
        _publish_result_events(result, dry_run=dry_run, request_id=request_id)
        return result

    if secret_errors:
        # Clusters whose tokens failed are missing from the client map, so the
        # partial result is accurate but the run as a whole did not succeed.
        result = EndpointsDiscoveryTaskResult(
            status=TaskStatus.FAILED,
            actions=result.actions,
            applied_actions=result.applied_actions,
            applied_count=result.applied_count,
            apps_with_changes=result.apps_with_changes,
            mr_status=result.mr_status,
            mr_url=result.mr_url,
            errors=[*secret_errors, *result.errors],
        )

    logger.info(
        f"Task {request_id} completed",
        status=result.status,
        total_actions=len(result.actions),
        applied_count=result.applied_count,
        apps_with_changes=result.apps_with_changes,
        mr_status=result.mr_status,
        mr_url=result.mr_url,
        errors=result.errors,
    )

    _publish_result_events(result, dry_run=dry_run, request_id=request_id)
    return result
