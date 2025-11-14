"""Tests for task utilities."""

# ruff: noqa: PLR2004 - Magic values acceptable in tests for readability
import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from qontract_api.models import TaskStatus
from qontract_api.tasks.utils import wait_for_task_completion


class MockTaskResult(BaseModel):
    """Mock task result for testing."""

    status: TaskStatus
    data: str = "test"


@pytest.mark.asyncio
async def test_wait_for_task_non_blocking() -> None:
    """Non-blocking returns immediately with current status."""
    mock_result = MockTaskResult(status=TaskStatus.PENDING)

    result = await wait_for_task_completion(
        get_task_status=lambda: mock_result,
        timeout_seconds=None,
    )

    assert result.status == TaskStatus.PENDING
    assert result.data == "test"


@pytest.mark.asyncio
async def test_wait_for_task_blocking_success() -> None:
    """Blocking returns when task completes successfully."""
    mock_result = MockTaskResult(status=TaskStatus.SUCCESS)

    result = await wait_for_task_completion(
        get_task_status=lambda: mock_result,
        timeout_seconds=10,
    )

    assert result.status == TaskStatus.SUCCESS


@pytest.mark.asyncio
async def test_wait_for_task_blocking_failed() -> None:
    """Blocking returns when task fails."""
    mock_result = MockTaskResult(status=TaskStatus.FAILED)

    result = await wait_for_task_completion(
        get_task_status=lambda: mock_result,
        timeout_seconds=10,
    )

    assert result.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_wait_for_task_blocking_timeout() -> None:
    """Blocking raises 408 after timeout if still pending."""
    mock_result = MockTaskResult(status=TaskStatus.PENDING)

    with pytest.raises(HTTPException) as exc:
        await wait_for_task_completion(
            get_task_status=lambda: mock_result,
            timeout_seconds=1,
        )

    assert exc.value.status_code == 408
    assert "still pending after 1s" in exc.value.detail


@pytest.mark.asyncio
async def test_wait_for_task_eventually_completes() -> None:
    """Task that becomes complete during polling."""
    call_count = 0

    def get_status() -> MockTaskResult:
        nonlocal call_count
        call_count += 1
        # Return PENDING first 2 times, then SUCCESS
        if call_count <= 2:
            return MockTaskResult(status=TaskStatus.PENDING)
        return MockTaskResult(status=TaskStatus.SUCCESS, data="completed")

    result = await wait_for_task_completion(
        get_task_status=get_status,
        timeout_seconds=5,
        poll_interval=0.1,
    )

    assert result.status == TaskStatus.SUCCESS
    assert result.data == "completed"
    assert call_count >= 3
