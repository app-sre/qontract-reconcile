"""Tests for @with_hooks class decorator.

Covers automatic hook initialization, merging of built-in and user hooks,
hook execution order, retry config preservation, and error handling.
"""

# ruff: noqa: ARG001
from typing import Any

import pytest

# ruff: noqa: ARG002
from qontract_utils.hooks import Hooks, RetryConfig, invoke_with_hooks, with_hooks


def test_basic() -> None:
    """Test basic @with_hooks decorator functionality."""
    execution_order: list[str] = []

    def decorator_pre_hook(_ctx: Any) -> None:
        execution_order.append("decorator_pre")

    def decorator_post_hook(_ctx: Any) -> None:
        execution_order.append("decorator_post")

    @with_hooks(
        hooks=Hooks(
            pre_hooks=[decorator_pre_hook],
            post_hooks=[decorator_post_hook],
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> str:
            execution_order.append("main")
            return "result"

    api = TestApi()
    result = api.do_work()

    assert result == "result"
    assert execution_order == ["decorator_pre", "main", "decorator_post"]


def test_merges_user_hooks() -> None:
    """Test that decorator hooks are merged with user hooks."""
    execution_order: list[str] = []

    def decorator_pre_hook(_ctx: Any) -> None:
        execution_order.append("decorator_pre")

    def user_pre_hook(_ctx: Any) -> None:
        execution_order.append("user_pre")

    def decorator_post_hook(_ctx: Any) -> None:
        execution_order.append("decorator_post")

    def user_post_hook(_ctx: Any) -> None:
        execution_order.append("user_post")

    @with_hooks(
        hooks=Hooks(
            pre_hooks=[decorator_pre_hook],
            post_hooks=[decorator_post_hook],
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> str:
            execution_order.append("main")
            return "result"

    # Create instance with user hooks
    api = TestApi(
        hooks=Hooks(
            pre_hooks=[user_pre_hook],
            post_hooks=[user_post_hook],
        )
    )
    api.do_work()

    # Decorator hooks should run BEFORE user hooks
    assert execution_order == [
        "decorator_pre",
        "user_pre",
        "main",
        "decorator_post",
        "user_post",
    ]


def test_hook_execution_order() -> None:
    """Test that decorator hooks run before user hooks."""
    execution_order: list[str] = []

    def hook1(_ctx: Any) -> None:
        execution_order.append("hook1")

    def hook2(_ctx: Any) -> None:
        execution_order.append("hook2")

    def hook3(_ctx: Any) -> None:
        execution_order.append("hook3")

    @with_hooks(
        hooks=Hooks(
            pre_hooks=[hook1, hook2],
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi(hooks=Hooks(pre_hooks=[hook3]))
    api.do_work()

    # Decorator hooks (hook1, hook2) should run before user hooks (hook3)
    assert execution_order == ["hook1", "hook2", "hook3", "main"]


def test_preserves_retry_config() -> None:
    """Test that user retry configuration is preserved."""

    @with_hooks(
        hooks=Hooks(
            pre_hooks=[],
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

    custom_retry = RetryConfig(on=Exception, attempts=10, wait_initial=5.0)
    api = TestApi(hooks=Hooks(retry_config=custom_retry))

    # Verify retry config is preserved
    assert api._hooks.retry_config == custom_retry  # type: ignore[attr-defined]


def test_none_hooks() -> None:
    """Test that decorator handles hooks=None correctly."""
    execution_order: list[str] = []

    def decorator_hook(_ctx: Any) -> None:
        execution_order.append("decorator")

    @with_hooks(
        hooks=Hooks(
            pre_hooks=[decorator_hook],
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> None:
            execution_order.append("main")

    # Create instance with hooks=None (default)
    api = TestApi(hooks=None)
    api.do_work()

    # Should still run decorator hooks
    assert execution_order == ["decorator", "main"]


def test_no_hooks_param_raises_error() -> None:
    """Test that decorator raises error if __init__ has no hooks parameter."""

    @with_hooks(hooks=Hooks(pre_hooks=[]))
    class BadApi:
        def __init__(self) -> None:  # Missing hooks parameter!
            pass

    # Error is raised when creating instance, not when decorating
    with pytest.raises(ValueError, match="must have a 'hooks' parameter in __init__"):
        BadApi()


def test_with_other_params() -> None:
    """Test that decorator works with other __init__ parameters."""
    execution_order: list[str] = []

    def decorator_hook(_ctx: Any) -> None:
        execution_order.append("decorator")

    @with_hooks(
        hooks=Hooks(
            pre_hooks=[decorator_hook],
        )
    )
    class TestApi:
        def __init__(
            self,
            api_url: str,
            token: str,
            timeout: int = 30,
            hooks: Hooks | None = None,
        ) -> None:
            self.api_url = api_url
            self.token = token
            self.timeout = timeout

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> None:
            execution_order.append("main")

    # Create instance with all parameters
    api = TestApi(api_url="https://api.example.com", token="secret", timeout=60)
    api.do_work()

    assert api.api_url == "https://api.example.com"
    assert api.token == "secret"
    assert api.timeout == 60
    assert execution_order == ["decorator", "main"]


def test_empty_decorator_hooks() -> None:
    """Test decorator with empty hooks."""
    execution_order: list[str] = []

    def user_hook(_ctx: Any) -> None:
        execution_order.append("user")

    @with_hooks(hooks=Hooks())  # Empty hooks
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi(hooks=Hooks(pre_hooks=[user_hook]))
    api.do_work()

    # Only user hooks should run
    assert execution_order == ["user", "main"]


def test_merges_error_hooks() -> None:
    """Test that decorator error hooks are merged with user error hooks."""
    execution_order: list[str] = []

    def decorator_error_hook(_ctx: Any) -> None:
        execution_order.append("decorator_error")

    def user_error_hook(_ctx: Any) -> None:
        execution_order.append("user_error")

    @with_hooks(
        hooks=Hooks(
            error_hooks=[decorator_error_hook],
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> str:
            execution_order.append("main")
            raise RuntimeError("boom")

    api = TestApi(
        hooks=Hooks(
            error_hooks=[user_error_hook],
        )
    )

    with pytest.raises(RuntimeError, match="boom"):
        api.do_work()

    # Decorator error hooks should run BEFORE user error hooks
    assert execution_order == ["main", "decorator_error", "user_error"]


def test_merges_retry_hooks(enable_retry: None) -> None:
    """Test that decorator retry hooks are merged with user retry hooks."""
    execution_order: list[str] = []
    call_count = 0

    def decorator_retry_hook(_ctx: Any, attempt: int) -> None:
        execution_order.append(f"decorator_retry:{attempt}")

    def user_retry_hook(_ctx: Any, attempt: int) -> None:
        execution_order.append(f"user_retry:{attempt}")

    @with_hooks(
        hooks=Hooks(
            retry_hooks=[decorator_retry_hook],
            retry_config=RetryConfig(
                on=RuntimeError, attempts=3, wait_initial=0, wait_max=0, wait_jitter=0
            ),
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda _: {"test": "context"})
        def do_work(self) -> str:
            nonlocal call_count
            call_count += 1
            execution_order.append(f"main:{call_count}")
            if call_count < 2:
                raise RuntimeError("fail")
            return "ok"

    api = TestApi(
        hooks=Hooks(
            retry_hooks=[user_retry_hook],
        )
    )
    result = api.do_work()

    assert result == "ok"
    # First attempt fails, second attempt succeeds with retry hooks called
    assert execution_order == [
        "main:1",
        "decorator_retry:2",
        "user_retry:2",
        "main:2",
    ]


def test_retry_config_decorator_only() -> None:
    """Test that decorator retry_config takes precedence over user retry_config."""
    decorator_retry = RetryConfig(on=Exception, attempts=5, wait_initial=1.0)

    @with_hooks(
        hooks=Hooks(
            retry_config=decorator_retry,
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

    api = TestApi()

    # Decorator retry_config should take precedence
    assert api._hooks.retry_config == decorator_retry  # type: ignore[attr-defined]


def test_retry_config_user_takes_precedence() -> None:
    """Test that decorator retry_config takes precedence over user retry_config."""
    decorator_retry = RetryConfig(on=Exception, attempts=5, wait_initial=1.0)
    user_retry = RetryConfig(on=Exception, attempts=10, wait_initial=2.0)

    @with_hooks(
        hooks=Hooks(
            retry_config=decorator_retry,
        )
    )
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

    api = TestApi(hooks=Hooks(retry_config=user_retry))

    # Decorator retry_config should take precedence
    assert api._hooks.retry_config == user_retry  # type: ignore[attr-defined]


def test_retry_config_falls_back_to_user() -> None:
    """Test that user retry_config is used when decorator has none."""
    user_retry = RetryConfig(on=Exception, attempts=10, wait_initial=2.0)

    @with_hooks(hooks=Hooks())  # No retry_config in decorator
    class TestApi:
        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

    api = TestApi(hooks=Hooks(retry_config=user_retry))

    # User retry_config should be used as fallback
    assert api._hooks.retry_config == user_retry  # type: ignore[attr-defined]


def test_default_retry_config_is_none() -> None:
    """Test that default retry_config is None (not NO_RETRY_CONFIG)."""
    hooks = Hooks()
    assert hooks.retry_config is None
