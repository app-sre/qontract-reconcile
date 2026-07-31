"""Celery tasks for OCM OIDC identity provider reconciliation.

This module defines background tasks for reconciling OCM OIDC identity providers.
Tasks run in Celery workers, separate from the FastAPI application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.ocm_oidc_idp.schemas import OcmOidcIdpTaskResult
from qontract_api.integrations.ocm_oidc_idp.service import OcmOidcIdpService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.external.ocm.schemas import OcmConnectionParams
    from qontract_api.integrations.ocm_oidc_idp.domain import OcmOidcIdpCluster
    from qontract_api.models import Secret

logger = get_logger(__name__)


def generate_lock_key(
    _self: Task,
    ocm_environment: str,
    vault_target: Secret,
    **_: Any,
) -> str:
    """Generate lock key for task deduplication.

    Lock key is based on OCM environment + vault target path to prevent concurrent
    reconciliations for the same set of identity providers.
    """
    return f"{ocm_environment}:{vault_target.path}"


@celery_app.task(bind=True, name="ocm-oidc-idp.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_ocm_oidc_idp_task(
    self: Any,  # Celery Task instance (bind=True)
    ocm_environment: str,
    ocm_connection: OcmConnectionParams,
    clusters: list[OcmOidcIdpCluster],
    vault_target: Secret,
    *,
    dry_run: bool = True,
) -> OcmOidcIdpTaskResult:
    """Reconcile OCM OIDC identity providers (background task)."""
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        service = OcmOidcIdpService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.reconcile(
            ocm_environment=ocm_environment,
            ocm_connection=ocm_connection,
            clusters=clusters,
            vault_target=vault_target,
            dry_run=dry_run,
        )
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return OcmOidcIdpTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected {err=}"],
        )

    logger.info(
        f"Task {request_id} completed",
        status=result.status,
        total_actions=len(result.actions),
        applied_count=result.applied_count,
        errors=result.errors,
    )

    if not dry_run and event_manager:
        try:
            for action in result.applied_actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.ocm-oidc-idp.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )
            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.ocm-oidc-idp.error",
                        data={"error": error},
                        datacontenttype="application/json",
                    )
                )
        except Exception:
            logger.exception(f"Task {request_id} failed to publish events")

    return result
