"""Celery tasks for RHIDP SSO client reconciliation.

This module defines background tasks for reconciling RHIDP SSO clients. Tasks run in
Celery workers, separate from the FastAPI application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.sso_client.schemas import SsoClientTaskResult
from qontract_api.integrations.sso_client.service import SsoClientService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.sso_client.domain import (
        KeycloakInstanceSecret,
        SsoClientCluster,
    )
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
    reconciliations for the same set of SSO clients.
    """
    return f"{ocm_environment}:{vault_target.path}"


@celery_app.task(bind=True, name="sso-client.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_sso_client_task(
    self: Any,  # Celery Task instance (bind=True)
    ocm_environment: str,
    clusters: list[SsoClientCluster],
    keycloak_secrets: list[KeycloakInstanceSecret],
    vault_target: Secret,
    *,
    dry_run: bool = True,
) -> SsoClientTaskResult:
    """Reconcile RHIDP SSO clients (background task)."""
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        service = SsoClientService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.reconcile(
            ocm_environment=ocm_environment,
            clusters=clusters,
            keycloak_secrets=keycloak_secrets,
            vault_target=vault_target,
            dry_run=dry_run,
        )

        logger.info(
            f"Task {request_id} completed",
            status=result.status,
            total_actions=len(result.actions),
            applied_count=result.applied_count,
            errors=result.errors,
        )

        if not dry_run and event_manager:
            for action in result.applied_actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.sso-client.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )
            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.sso-client.error",
                        data={"error": error},
                        datacontenttype="application/json",
                    )
                )

        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        return SsoClientTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[str(e)],
        )
