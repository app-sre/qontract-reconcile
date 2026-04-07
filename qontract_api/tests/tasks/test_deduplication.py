"""Unit tests for task deduplication decorator."""

from unittest.mock import MagicMock, patch

import pytest

from qontract_api.models import TaskResult, TaskStatus
from qontract_api.tasks import deduplicated_task


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock cache backend."""
    mock = MagicMock()
    # Default: lock acquisition succeeds
    mock.lock.return_value.__enter__ = MagicMock()
    mock.lock.return_value.__exit__ = MagicMock(return_value=False)
    return mock


def test_deduplicated_task_success(mock_cache: MagicMock) -> None:
    """Test task executes when lock is acquired."""

    @deduplicated_task(lock_key_fn=lambda x: x, timeout=60)
    def test_task(x: str) -> str:
        return f"processed-{x}"

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        result = test_task("workspace-1")

    assert result == "processed-workspace-1"
    # Verify lock was attempted with correct key
    mock_cache.lock.assert_called_once_with(
        "task_lock:test_task:dry_run=true:workspace-1", timeout=60
    )


def test_deduplicated_task_skips_duplicate(mock_cache: MagicMock) -> None:
    """Test task skips execution when lock cannot be acquired (duplicate)."""

    @deduplicated_task(lock_key_fn=lambda x: x, timeout=60)
    def test_task(x: str) -> str:
        return f"processed-{x}"

    # Mock: lock acquisition fails (RuntimeError)
    mock_cache.lock.return_value.__enter__.side_effect = RuntimeError(
        "Lock not acquired"
    )

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        result = test_task("workspace-1")

    # Should return TaskResult with SKIPPED status, not a raw dict
    assert isinstance(result, TaskResult)
    assert result.status == TaskStatus.SKIPPED
    assert result.errors == ["duplicate_task"]


def test_deduplicated_task_preserves_concrete_subclass_on_skip(
    mock_cache: MagicMock,
) -> None:
    """Test skip result is an instance of the concrete TaskResult subclass."""

    class CustomTaskResult(TaskResult):
        pass

    @deduplicated_task(lock_key_fn=lambda x: x, timeout=60)
    def test_task(x: str) -> CustomTaskResult:
        return CustomTaskResult(status=TaskStatus.SUCCESS)

    mock_cache.lock.return_value.__enter__.side_effect = RuntimeError(
        "Lock not acquired"
    )

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        result = test_task("workspace-1")

    assert isinstance(result, CustomTaskResult)
    assert result.status == TaskStatus.SKIPPED
    assert result.errors == ["duplicate_task"]


def test_deduplicated_task_with_multiple_args(mock_cache: MagicMock) -> None:
    """Test lock key generation with multiple arguments."""

    @deduplicated_task(
        lock_key_fn=lambda x, y, **_: f"{x}-{y}",
        timeout=120,
    )
    def test_task(x: str, y: str, z: int = 0) -> str:
        return f"result-{x}-{y}-{z}"

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        result = test_task("a", "b", z=10)

    assert result == "result-a-b-10"
    # Verify lock key includes both x and y
    mock_cache.lock.assert_called_once_with(
        "task_lock:test_task:dry_run=true:a-b", timeout=120
    )


def test_deduplicated_task_lock_timeout(mock_cache: MagicMock) -> None:
    """Test task uses custom timeout for lock."""

    @deduplicated_task(lock_key_fn=lambda x: x, timeout=300)
    def test_task(x: str) -> str:
        return f"result-{x}"

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        test_task("workspace-1")

    # Verify custom timeout was used
    mock_cache.lock.assert_called_once_with(
        "task_lock:test_task:dry_run=true:workspace-1", timeout=300
    )


def test_deduplicated_task_releases_lock_on_exception(
    mock_cache: MagicMock,
) -> None:
    """Test lock is released even when task raises exception."""

    @deduplicated_task(lock_key_fn=lambda x: x, timeout=60)
    def test_task(x: str) -> str:
        raise ValueError("Task failed")

    with (
        patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache),
        pytest.raises(ValueError, match="Task failed"),
    ):
        test_task("workspace-1")

    # Lock context manager should still be entered and exited
    mock_cache.lock.return_value.__enter__.assert_called_once()
    mock_cache.lock.return_value.__exit__.assert_called_once()


def test_deduplicated_task_with_kwargs(mock_cache: MagicMock) -> None:
    """Test lock key generation with keyword arguments."""

    @deduplicated_task(
        lock_key_fn=lambda workspace, **_: workspace,
        timeout=60,
    )
    def test_task(workspace: str, *, dry_run: bool = True) -> dict[str, str | bool]:
        return {"workspace": workspace, "dry_run": dry_run}

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        result = test_task(workspace="test-ws", dry_run=False)

    assert result == {"workspace": "test-ws", "dry_run": False}
    mock_cache.lock.assert_called_once_with(
        "task_lock:test_task:dry_run=false:test-ws", timeout=60
    )


def test_deduplicated_task_dry_run_and_production_use_separate_keys(
    mock_cache: MagicMock,
) -> None:
    """dry_run=true and dry_run=false tasks must not share a lock key."""

    @deduplicated_task(lock_key_fn=lambda workspace, **_: workspace, timeout=60)
    def test_task(workspace: str, *, dry_run: bool = True) -> str:
        return workspace

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        test_task(workspace="ws-1", dry_run=True)
        test_task(workspace="ws-1", dry_run=False)

    calls = [call.args[0] for call in mock_cache.lock.call_args_list]
    assert calls[0] == "task_lock:test_task:dry_run=true:ws-1"
    assert calls[1] == "task_lock:test_task:dry_run=false:ws-1"
    assert calls[0] != calls[1]


def test_deduplicated_task_preserves_function_name() -> None:
    """Test decorator preserves original function name."""

    @deduplicated_task(lock_key_fn=lambda x: x, timeout=60)
    def my_custom_task(x: str) -> str:
        return x

    assert my_custom_task.__name__ == "my_custom_task"


def test_deduplicated_task_with_complex_lock_key(mock_cache: MagicMock) -> None:
    """Test lock key generation with complex key function."""

    @deduplicated_task(
        lock_key_fn=lambda workspaces, **_: ",".join(
            sorted(ws["name"] for ws in workspaces)
        ),
        timeout=600,
    )
    def test_task(workspaces: list[dict[str, str]]) -> int:
        return len(workspaces)

    workspaces = [
        {"name": "ws-b"},
        {"name": "ws-a"},
    ]

    with patch("qontract_api.tasks._deduplication.get_cache", return_value=mock_cache):
        result = test_task(workspaces)

    assert result == 2
    # Lock key should be sorted workspace names
    mock_cache.lock.assert_called_once_with(
        "task_lock:test_task:dry_run=true:ws-a,ws-b", timeout=600
    )
