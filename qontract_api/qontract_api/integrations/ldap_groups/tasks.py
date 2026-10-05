"""Celery tasks for ldap-groups reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.integrations.ldap_groups.schemas import LdapGroupsTaskResult
from qontract_api.integrations.ldap_groups.service import LdapGroupsService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.ldap_groups.domain import Group
    from qontract_api.internal_groups.domain import InternalGroupsConnectionSecret

logger = get_logger(__name__)


def generate_lock_key(
    _self: Task,
    connection: InternalGroupsConnectionSecret,
    *_args: Any,
    **_: Any,
) -> str:
    return f"ldap-groups:{connection.api_url}:{connection.client_id}"


@celery_app.task(bind=True, name="ldap-groups.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_ldap_groups_task(
    self: Any,
    connection: InternalGroupsConnectionSecret,
    desired_groups: list[Group],
    managed_group_names: list[str],
    *,
    dry_run: bool = True,
) -> LdapGroupsTaskResult:
    request_id = self.request.id
    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        service = LdapGroupsService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )
        result = service.reconcile(
            connection=connection,
            desired_groups=desired_groups,
            managed_group_names=managed_group_names,
            dry_run=dry_run,
        )
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return LdapGroupsTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected {err=}"],
            updated_managed_groups=sorted(managed_group_names),
        )

    logger.info(
        f"Task {request_id} completed",
        status=result.status,
        total_actions=len(result.actions),
        applied_count=result.applied_count,
        errors=result.errors,
    )
    return result
