"""Task deduplication using distributed locks via CacheBackend.

This module provides a decorator for Celery tasks to prevent duplicate
task execution using distributed locking through the CacheBackend abstraction.

Uses global cache instance (get_cache()) to avoid creating multiple connections.
"""

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from qontract_api.cache.factory import get_cache
from qontract_api.logger import get_logger

logger = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def deduplicated_task(
    lock_key_fn: Callable[..., str],
    timeout: int = 600,
) -> Callable[[Callable[P, R]], Callable[P, R | dict[str, str]]]:
    """Decorator for task deduplication using distributed locks via CacheBackend.

    Prevents multiple instances of the same task from running simultaneously.
    Uses CacheBackend.lock() which provides backend-specific locking:
    - Redis/Valkey: Native lock with Lua scripts + watch-dog
    - Other backends: Backend-specific distributed locking

    Args:
        lock_key_fn: Function to generate lock key from task arguments.
                    Example: `lambda workspace, **kw: workspace`
        timeout: Lock timeout in seconds (default: 600 = 10 minutes).
                TTL ensures lock is released even if task crashes.

    Returns:
        Decorated function that skips execution if lock cannot be acquired

    Example:
        @celery_app.task(bind=True)
        @deduplicated_task(lambda workspace, **kw: workspace, timeout=600)
        def reconcile_task(self, workspace: str, dry_run: bool):
            # Task logic - only one process at a time per workspace
            pass

    Usage Notes:
        - Lock key is: task_lock:{function_name}:{lock_key}
        - Non-blocking: Returns {"status": "skipped"} if duplicate detected
        - Lock is automatically released when function returns
        - Uses global cache (get_cache()) - shared across all tasks in worker
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R | dict[str, str]]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | dict[str, str]:
            # Generate lock key from task arguments
            lock_key_suffix = lock_key_fn(*args, **kwargs)
            lock_key = f"task_lock:{func.__name__}:{lock_key_suffix}"

            logger.debug(
                f"Attempting to acquire lock for task {func.__name__}",
                lock_key=lock_key,
                timeout=timeout,
            )

            # Try to acquire lock (non-blocking via exception handling)
            cache = get_cache()
            try:
                with cache.lock(lock_key, timeout=timeout):
                    logger.debug(
                        f"Lock acquired for task {func.__name__}",
                        lock_key=lock_key,
                        lock_key_suffix=lock_key_suffix,
                    )

                    # Execute task
                    result = func(*args, **kwargs)

                    logger.debug(
                        f"Lock released for task {func.__name__}",
                        lock_key=lock_key,
                        lock_key_suffix=lock_key_suffix,
                    )

                    return result

            except RuntimeError:
                # Lock could not be acquired - duplicate task is running
                logger.warning(
                    f"Task {func.__name__} already running, skipping duplicate",
                    lock_key=lock_key,
                    lock_key_suffix=lock_key_suffix,
                )
                return {"status": "skipped", "reason": "duplicate_task"}

        return wrapper

    return decorator
