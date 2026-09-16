"""Celery tasks for managed-sso-client reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.managed_sso_client.metrics import INTEGRATION_NAME
from qontract_api.integrations.managed_sso_client.schemas import (
    ManagedSsoClientErrorEvent,
    ManagedSsoClientTaskResult,
)
from qontract_api.integrations.managed_sso_client.service import (
    ManagedSsoClientService,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.managed_sso_client.domain import (
        ManagedSsoClientDesiredState,
    )

logger = get_logger(__name__)


def generate_lock_key(_self: Task, **_: Any) -> str:
    """Lock key for managed-sso-client reconciliation.

    A constant, not derived from any argument: the AppSRE-owned management
    Vault prefix is entirely server-configured (settings.managed_sso_client.
    vault_path_prefix), so every reconcile call targets the exact same
    prefix - there's no per-call variability left to key on, and two
    concurrent calls must never run regardless of which desired_clients they
    carry (they'd list/diff/write against the same Vault prefix and could
    race on shared clients).
    """
    return INTEGRATION_NAME


@celery_app.task(bind=True, name="managed-sso-client.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_managed_sso_client_task(
    self: Any,
    desired_clients: list[ManagedSsoClientDesiredState],
    *,
    dry_run: bool = True,
) -> ManagedSsoClientTaskResult:
    """Reconcile managed SSO clients (background task)."""
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        service = ManagedSsoClientService(
            secret_manager=secret_manager,
            cache=cache,
            settings=settings,
        )

        result = service.reconcile(
            desired_clients=desired_clients,
            dry_run=dry_run,
        )
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return ManagedSsoClientTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected {err=}"],
        )

    logger.info(
        f"Task {request_id} completed",
        status=result.status,
        total_actions=len(result.actions),
        applied_count=len(result.applied_actions),
        errors=result.errors,
    )

    if not dry_run and event_manager:
        try:
            for action in result.applied_actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.managed-sso-client.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )
            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.managed-sso-client.error",
                        data=ManagedSsoClientErrorEvent(error=error).model_dump(
                            mode="json"
                        ),
                        datacontenttype="application/json",
                    )
                )
        except Exception:
            logger.exception(f"Task {request_id} failed to publish events")

    return result
