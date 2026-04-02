"""Celery tasks for AWS account manager.

Per-account design: each task handles exactly one account.
"""

from typing import Any

from celery import Task
from qontract_utils.events import Event

from qontract_api.cache import clear_workflow_cache
from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.aws_account_manager.schemas import (
    AWSAccountManagerCreateAccountRequest,
    AWSAccountManagerCreateIAMUserRequest,
    AWSAccountManagerReconcileRequest,
    CreateAccountResult,
    CreateIAMUserResult,
    ReconcileResult,
)
from qontract_api.integrations.aws_account_manager.service import (
    AccountCreationInProgressError,
    AWSAccountManagerService,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

logger = get_logger(__name__)

_EVENT_PREFIX = "qontract-api.aws-account-manager"


def _publish_action_events(
    *,
    result: ReconcileResult | CreateAccountResult | CreateIAMUserResult,
    dry_run: bool,
    event_type_prefix: str,
) -> None:
    """Publish events for each action in a task result."""
    if dry_run or not (event_manager := get_event_manager()):
        return
    for action in result.actions:
        event_manager.publish_event(
            Event(
                source=__name__,
                type=f"{event_type_prefix}.{action.action_type}",
                data=action.model_dump(mode="json"),
                datacontenttype="application/json",
            ),
        )


def generate_create_account_lock_key(
    _self: Task,
    request: AWSAccountManagerCreateAccountRequest,
    **_: Any,
) -> str:
    """Lock key: payer_name:request_name."""
    return f"{request.payer_account.name}:{request.account_request.name}"


def generate_create_iam_user_lock_key(
    _self: Task,
    request: AWSAccountManagerCreateIAMUserRequest,
    **_: Any,
) -> str:
    """Lock key: payer_name:account_name:user_name."""
    return f"{request.payer_account.name}:{request.account_name}:{request.user_name}"


def generate_reconcile_lock_key(
    _self: Task,
    request: AWSAccountManagerReconcileRequest,
    **_: Any,
) -> str:
    """Lock key: payer_uid:account_name (or standalone:account_name)."""
    prefix = request.payer_uid or "standalone"
    return f"{prefix}:{request.account_name}"


@celery_app.task(
    bind=True,
    name="aws-account-manager.create-account",
    acks_late=True,
    max_retries=120,
)
@deduplicated_task(lock_key_fn=generate_create_account_lock_key, timeout=1500)
def create_account_task(
    self: Any,
    request: AWSAccountManagerCreateAccountRequest,
    workflow_id: str,
) -> CreateAccountResult:
    """Create a single AWS account (background task).

    Executes the multi-step account creation workflow. If the workflow is not
    yet complete (e.g. AWS account still being provisioned), the task retries
    itself after a countdown — no client re-invocation needed.
    """
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        service = AWSAccountManagerService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.create_account(
            payer_account=request.payer_account,
            account_request=request.account_request,
            default_tags=request.default_tags,
            dry_run=request.dry_run,
        )

        logger.info(
            f"Task {request_id} completed",
            status=result.status,
            total_actions=len(result.actions),
            applied_count=result.applied_count,
            actions=[action.model_dump() for action in result.actions],
            errors=result.errors,
        )

        _publish_action_events(
            result=result,
            dry_run=request.dry_run,
            event_type_prefix=f"{_EVENT_PREFIX}.create-account",
        )

        return result

    except AccountCreationInProgressError:
        logger.info("Task %s retrying — account creation in progress", request_id)
        raise self.retry(countdown=10) from None

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        clear_workflow_cache(get_cache(), workflow_id)
        return CreateAccountResult(
            status=TaskStatus.FAILED,
            errors=[str(e)],
        )


@celery_app.task(bind=True, name="aws-account-manager.create-iam-user", acks_late=True)
@deduplicated_task(lock_key_fn=generate_create_iam_user_lock_key, timeout=600)
def create_iam_user_task(
    self: Any,
    request: AWSAccountManagerCreateIAMUserRequest,
) -> CreateIAMUserResult:
    """Create an IAM user in an AWS account (background task).

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.
    """
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        service = AWSAccountManagerService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.create_iam_user(
            payer_account=request.payer_account,
            account_name=request.account_name,
            account_uid=request.account_uid,
            org_role=request.organization_account_role,
            user_name=request.user_name,
            policy_arn=request.policy_arn,
            secret_vault_path=request.secret_vault_path,
            dry_run=request.dry_run,
        )

        logger.info(
            f"Task {request_id} completed",
            status=result.status,
            total_actions=len(result.actions),
            applied_count=result.applied_count,
            actions=[action.model_dump() for action in result.actions],
            errors=result.errors,
        )

        _publish_action_events(
            result=result,
            dry_run=request.dry_run,
            event_type_prefix=f"{_EVENT_PREFIX}.create-iam-user",
        )

        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        return CreateIAMUserResult(
            status=TaskStatus.FAILED,
            errors=[str(e)],
        )


@celery_app.task(bind=True, name="aws-account-manager.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_reconcile_lock_key, timeout=600)
def reconcile_account_task(
    self: Any,
    request: AWSAccountManagerReconcileRequest,
) -> ReconcileResult:
    """Reconcile a single AWS account (background task).

    Reconciles one account to match desired state: tags, OU, alias, quotas,
    enterprise support, security contact, and regions.
    """
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        service = AWSAccountManagerService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.reconcile(
            account=request,
            dry_run=request.dry_run,
        )

        logger.info(
            f"Task {request_id} completed",
            status=result.status,
            total_actions=len(result.actions),
            applied_count=result.applied_count,
            actions=[action.model_dump() for action in result.actions],
            errors=result.errors,
        )

        _publish_action_events(
            result=result,
            dry_run=request.dry_run,
            event_type_prefix=f"{_EVENT_PREFIX}.reconcile",
        )

        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        return ReconcileResult(
            status=TaskStatus.FAILED,
            errors=[str(e)],
        )
