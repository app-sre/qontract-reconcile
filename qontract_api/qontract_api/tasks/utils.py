"""Utilities for background task management."""

import asyncio
import time
from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

from fastapi import HTTPException, status

from qontract_api.models import TaskStatus


@runtime_checkable
class TaskResult(Protocol):
    """Protocol for task results with status attribute.

    This protocol works with both mutable and frozen (immutable) Pydantic models.
    """

    @property
    def status(self) -> TaskStatus:
        """Task execution status."""
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
