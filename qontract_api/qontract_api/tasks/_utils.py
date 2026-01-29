"""Utilities for background task management."""

# ruff: noqa: PLR6301, ARG002
import asyncio
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar, runtime_checkable

from billiard.einfo import ExceptionInfo
from celery import Task, states
from celery.result import AsyncResult
from fastapi import HTTPException, status
from hvac.exceptions import VaultError

from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

logger = get_logger(__name__)


@runtime_checkable
class TaskResult(Protocol):
    """Protocol for task results with status attribute."""

    @property
    def status(self) -> TaskStatus:
        """Task execution status."""
        ...

    @property
    def applied_count(self) -> int:
        """Number of applied actions."""
        ...

    @property
    def actions(self) -> list:
        """List of actions performed or calculated."""
        ...

    @property
    def errors(self) -> list[str]:
        """List of error messages, if any."""
        ...

    def __init__(
        self,
        *,
        status: TaskStatus,
        actions: list,
        applied_count: int,
        errors: list[str],
    ) -> None:
        """Construct a task result instance."""
        ...


T = TypeVar("T", bound=TaskResult)  # Generic result type with status


async def wait_for_task_completion[T: TaskResult](
    get_task_status: Callable[[], T],
    timeout_seconds: int | None,
    poll_interval: float = 0.5,
) -> T:
    """Wait for task completion with optional timeout.

    Generic helper for blocking GET endpoints. Works with any task result model
    that has a 'status' field using TaskStatus enum.

    Args:
        get_task_status: Function that returns current task status/result.
                        Must return object with .status attribute.
        timeout_seconds: Seconds to wait. None = return immediately (non-blocking).
        poll_interval: Seconds between status checks (default: 0.5s)

    Returns:
        Task result when complete (status = SUCCESS or FAILED) or immediately if timeout_seconds=None

    Raises:
        HTTPException 408: Task still PENDING after timeout_seconds

    Example:
        result = await wait_for_task_completion(
            get_task_status=lambda: get_slack_task(task_id, cache),
            timeout_seconds=60,
        )
    """
    # Non-blocking: return current status immediately
    if timeout_seconds is None:
        return get_task_status()

    # Blocking: poll until complete or timeout
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        result = get_task_status()

        # Task complete (success or failed)
        completed_statuses = {TaskStatus.SUCCESS, TaskStatus.FAILED}
        if result.status in completed_statuses:
            return result

        # Still pending, wait before next check
        await asyncio.sleep(poll_interval)

    # Timeout reached, task still pending
    raise HTTPException(
        status_code=status.HTTP_408_REQUEST_TIMEOUT,
        detail=f"Task still pending after {timeout_seconds}s",
    )


def get_celery_task_result[T: TaskResult](
    task_id: str,
    result_cls: type[T],
) -> T:
    """Get Celery task result with generic status mapping.

    Generic helper for retrieving Celery task results. Maps Celery states to
    TaskStatus and handles common patterns (deduplication, errors, pending).

    Args:
        task_id: Celery task ID
        result_cls: TaskResult class to instantiate (must have status field)

    Returns:
        Task result with status, actions, applied_count, errors

    Celery State Mapping:
        SUCCESS → Return result (pickle-deserialized Pydantic model)
        FAILED → TaskStatus.FAILED with error message
        PENDING/STARTED/RETRY → TaskStatus.PENDING (task not done yet)

    Special Cases:
        - Deduplication skip: {"status": "skipped"} → TaskStatus.SUCCESS
        - Unexpected result type → ValueError
    """
    async_result = AsyncResult(task_id)
    match async_result.state:
        case states.SUCCESS:
            result = async_result.result

            # Special case: Deduplication skip (from @deduplicated_task)
            if isinstance(result, dict) and result.get("status") == "skipped":
                logger.info(
                    f"Task {task_id} was skipped (duplicate)",
                    task_id=task_id,
                    reason=result.get("reason"),
                )
                # Construct result (result_cls is a Pydantic model, not Protocol)
                return result_cls(
                    status=TaskStatus.SUCCESS,
                    actions=[],
                    applied_count=0,
                    errors=[f"Task skipped: {result.get('reason')}"],
                )

            # Normal success: Result is already Pydantic model (pickle deserialization)
            if isinstance(result, result_cls):
                return result

            # Unexpected result type - should not happen with pickle
            msg = f"Unexpected result type for task {task_id}: {type(result)}"
            logger.error(msg, task_id=task_id, result_type=type(result))
            raise ValueError(msg)

        case states.FAILURE:
            error_msg = (
                str(async_result.result) if async_result.result else "Unknown error"
            )
            logger.error(f"Task {task_id} failed", task_id=task_id, error=error_msg)
            return result_cls(
                status=TaskStatus.FAILED,
                actions=[],
                applied_count=0,
                errors=[error_msg],
            )

        case _:
            # PENDING/STARTED/RETRY: Task not done yet
            logger.debug(
                f"Task {task_id} still pending",
                task_id=task_id,
                celery_state=async_result.state,
            )
            return result_cls(
                status=TaskStatus.PENDING,
                actions=[],
                applied_count=0,
                errors=[],
            )


class BackgroundTask(Task):
    autoretry_for = (VaultError,)
    default_retry_delay = 5
    max_retries = 3

    def before_start(self, *_: Any, **__: Any) -> None:
        logger.info("Initializing task", status=TaskStatus.PENDING)

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        logger.info("Task succeeded", status=TaskStatus.SUCCESS, result="ok")

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: ExceptionInfo,
    ) -> None:
        logger.error("Task failed", status=TaskStatus.FAILED, result=str(exc))

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: ExceptionInfo,
    ) -> None:
        logger.info("Task retrying", status=TaskStatus.PENDING, error=str(exc))
