"""Tests for retry system with stamina integration.

Covers RetryConfig, retry hooks, retry lifecycle, and retry_config override.
"""

from typing import Any

import pytest
import structlog

# ruff: noqa: ARG001
from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, RetryConfig, invoke_with_hooks
from structlog.typing import EventDict


def test_retry_config_defaults() -> None:
    """Test RetryConfig uses stamina defaults."""
    config = RetryConfig(on=RuntimeError)
    assert config.attempts == 10
    assert config.timeout == 45.0
    assert config.wait_initial == 0.1
    assert config.wait_max == 5.0
    assert config.wait_jitter == 1.0
    assert config.wait_exp_base == 2


def test_no_retry_config_constant() -> None:
    """Test NO_RETRY_CONFIG prevents retries."""
    assert NO_RETRY_CONFIG.attempts == 1
    assert NO_RETRY_CONFIG.on is Exception


def test_retry_with_success_on_first_attempt(enable_retry: None) -> None:
    """Test retry config allows successful first attempt."""
    execution_count = {"count": 0}

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                )
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1

    api = TestApi()
    api.do_work()
    assert execution_count["count"] == 1


def test_retry_on_exception(enable_retry: None) -> None:
    """Test retry logic retries on configured exception."""
    execution_count = {"count": 0}

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                )
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()
    assert execution_count["count"] == 3


def test_retry_hooks_called_on_retry_only(enable_retry: None) -> None:
    """Test retry hooks called before retries (not first attempt)."""
    retry_hook_calls: list[int] = []
    execution_count = {"count": 0}

    def retry_hook(attempt_num: int) -> None:
        retry_hook_calls.append(attempt_num)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                retry_hooks=[retry_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()
    # Retry hooks on attempts 2, 3 (not on first)
    assert retry_hook_calls == [2, 3]


def test_pre_hooks_only_on_first_attempt(enable_retry: None) -> None:
    """Test pre-hooks run only once."""
    pre_hook_calls = {"count": 0}
    execution_count = {"count": 0}

    def pre_hook() -> None:
        pre_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()
    assert pre_hook_calls["count"] == 1  # Only once


def test_post_hooks_always_called(enable_retry: None) -> None:
    """Test post-hooks always run (finally semantics)."""
    post_hook_calls = {"count": 0}
    execution_count = {"count": 0}

    def post_hook() -> None:
        post_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                post_hooks=[post_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()
    # Post-hook called once (finally block after success)
    assert post_hook_calls["count"] == 1


def test_post_hooks_on_failure(enable_retry: None) -> None:
    """Test post-hooks run even after final failure (finally)."""
    post_hook_calls = {"count": 0}

    def post_hook() -> None:
        post_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                post_hooks=[post_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            raise ValueError("always fails")

    api = TestApi()
    with pytest.raises(ValueError, match="always fails"):
        api.do_work()

    # Post-hook called once (finally block after failure)
    assert post_hook_calls["count"] == 1


def test_error_hooks_only_on_final_failure(enable_retry: None) -> None:
    """Test error-hooks only called when all retries exhausted."""
    error_hook_calls = {"count": 0}
    execution_count = {"count": 0}

    def error_hook() -> None:
        error_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                error_hooks=[error_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()
    # Error hook NOT called (success on attempt 3)
    assert error_hook_calls["count"] == 0


def test_error_hooks_on_exhausted_retries(enable_retry: None) -> None:
    """Test error-hooks called when all retries exhausted."""
    error_hook_calls = {"count": 0}

    def error_hook() -> None:
        error_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                error_hooks=[error_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            raise ValueError("always fails")

    api = TestApi()
    with pytest.raises(ValueError, match="always fails"):
        api.do_work()

    # Error hook called once in except block
    assert error_hook_calls["count"] == 1


def test_retry_max_attempts_exceeded(enable_retry: None) -> None:
    """Test retry gives up after max attempts."""
    execution_count = {"count": 0}

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                retry_config=RetryConfig(
                    on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001
                )
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            raise ValueError("always fails")

    api = TestApi()
    with pytest.raises(ValueError, match="always fails"):
        api.do_work()

    # Called 3 times (attempts=3)
    assert execution_count["count"] == 3


def test_retry_with_different_exception(enable_retry: None) -> None:
    """Test no retry for non-configured exceptions."""
    execution_count = {"count": 0}

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                )
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            raise RuntimeError("different exception")

    api = TestApi()
    with pytest.raises(RuntimeError):
        api.do_work()

    # Only called once (no retry for RuntimeError)
    assert execution_count["count"] == 1


def test_retry_with_full_hook_lifecycle(enable_retry: None) -> None:
    """Test all hooks combined with retry."""
    execution_log: list[str] = []
    execution_count = {"count": 0}

    def pre_hook() -> None:
        execution_log.append("pre")

    def post_hook() -> None:
        execution_log.append("post")

    def error_hook() -> None:
        execution_log.append("error")

    def retry_hook(attempt: int) -> None:
        execution_log.append(f"retry-{attempt}")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                error_hooks=[error_hook],
                retry_hooks=[retry_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=4, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            execution_log.append(f"main-{execution_count['count']}")
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()
    # pre -> main-1 -> retry-2 -> main-2 -> retry-3 -> main-3 -> post
    assert execution_log == [
        "pre",
        "main-1",
        "retry-2",
        "main-2",
        "retry-3",
        "main-3",
        "post",
    ]


def test_stamina_logging_shows_callable_name(enable_retry: None) -> None:
    """Test stamina logs show meaningful callable name instead of '<context block>'."""
    captured_logs: list[dict[str, Any]] = []

    def capture_processor(
        _logger: Any, _method_name: str, event_dict: EventDict
    ) -> EventDict:
        """Capture all log events."""
        captured_logs.append(dict(event_dict))
        return event_dict

    # Configure structlog to capture logs
    structlog.configure(
        processors=[
            capture_processor,
            structlog.processors.JSONRenderer(),
        ],
    )

    execution_count = {"count": 0}

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                )
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_count["count"] += 1
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()

    # Find retry_scheduled log events
    retry_logs = [
        log for log in captured_logs if log.get("event") == "stamina.retry_scheduled"
    ]

    # Should have retry logs (attempts 2 and 3)
    assert len(retry_logs) >= 1, f"Expected retry logs, got: {captured_logs}"

    # Check that callable is set to meaningful name, not '<context block>'
    for log in retry_logs:
        callable_name = log.get("callable")
        assert callable_name == "TestApi.do_work", (
            f"Expected callable='TestApi.do_work', got '{callable_name}'"
        )
        assert callable_name != "<context block>", (
            "Callable should not be '<context block>'"
        )


def test_retry_config_override_in_decorator() -> None:
    """Test decorator retry_config parameter overrides instance._hooks.retry_config."""
    execution_count = {"count": 0}

    class TestApi:
        def __init__(self) -> None:
            # Instance has retry enabled
            self._hooks = Hooks(
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                )
            )

        # Override: disable retry for this specific method
        @invoke_with_hooks(retry_config=NO_RETRY_CONFIG)
        def no_retry_method(self) -> None:
            execution_count["count"] += 1
            raise ValueError("should not retry")

    api = TestApi()
    with pytest.raises(ValueError, match="should not retry"):
        api.no_retry_method()

    # Should only be called once (no retry due to NO_RETRY_CONFIG)
    assert execution_count["count"] == 1


def test_retry_config_override_still_calls_hooks() -> None:
    """Test that overriding retry_config still executes other hooks."""
    execution_log: list[str] = []

    def pre_hook() -> None:
        execution_log.append("pre")

    def post_hook() -> None:
        execution_log.append("post")

    def error_hook() -> None:
        execution_log.append("error")

    class TestApi:
        def __init__(self) -> None:
            # Instance has retry enabled (but will be overridden)
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                error_hooks=[error_hook],
                retry_config=RetryConfig(
                    on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
                ),
            )

        @invoke_with_hooks(retry_config=NO_RETRY_CONFIG)
        def test_method(self) -> None:
            execution_log.append("main")
            raise ValueError("error")

    api = TestApi()
    with pytest.raises(ValueError, match="error"):
        api.test_method()

    # All hooks should run even with NO_RETRY_CONFIG
    assert execution_log == ["pre", "main", "error", "post"]
