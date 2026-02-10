"""Tests for Hooks.invoke() and Hooks.with_context().invoke().

Covers direct invocation pattern for one-off function calls without decorators.
"""

from typing import Any

import pytest

# ruff: noqa: ARG001
from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, RetryConfig


def test_invoke_basic() -> None:
    """Test execute via method call instead of decorator."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    def do_work(*args: Any, **kwargs: Any) -> str:
        assert args == ("arg1", "arg2")
        assert kwargs == {"kwarg1": "value1", "kwarg2": "value2"}
        execution_order.append("main")
        return "result"

    hooks = Hooks(pre_hooks=[pre_hook])
    r = hooks.invoke(do_work, "arg1", "arg2", kwarg1="value1", kwarg2="value2")
    assert r == "result"
    assert execution_order == ["pre", "main"]


def test_invoke_with_context() -> None:
    """Test execute via method call with context."""
    context_data: dict[str, Any] = {"access": True}

    def pre_hook(ctx: dict[str, Any]) -> None:
        assert ctx["access"]
        ctx["modified"] = True

    def do_work(*args: Any, **kwargs: Any) -> None: ...

    hooks = Hooks(pre_hooks=[pre_hook])
    hooks.with_context(context_data).invoke(
        do_work, "arg1", "arg2", kwarg1="value1", kwarg2="value2"
    )
    assert context_data["modified"] is True


def test_invoke_with_post_hooks() -> None:
    """Test invoke with post hooks."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    def post_hook() -> None:
        execution_order.append("post")

    def do_work() -> str:
        execution_order.append("main")
        return "result"

    hooks = Hooks(
        pre_hooks=[pre_hook], post_hooks=[post_hook], retry_config=NO_RETRY_CONFIG
    )
    result = hooks.invoke(do_work)
    assert result == "result"
    assert execution_order == ["pre", "main", "post"]


def test_invoke_with_error_hooks() -> None:
    """Test invoke with error hooks on exception."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    def error_hook() -> None:
        execution_order.append("error")

    def post_hook() -> None:
        execution_order.append("post")

    def do_work() -> None:
        execution_order.append("main")
        raise ValueError("test error")

    hooks = Hooks(
        pre_hooks=[pre_hook],
        post_hooks=[post_hook],
        error_hooks=[error_hook],
        retry_config=NO_RETRY_CONFIG,
    )

    with pytest.raises(ValueError, match="test error"):
        hooks.invoke(do_work)

    # Post hooks run in finally, error hooks run in except
    assert execution_order == ["pre", "main", "error", "post"]


def test_invoke_with_retry_hooks(enable_retry: None) -> None:
    """Test invoke with retry hooks."""
    execution_order: list[str] = []
    attempt_count = 0

    def pre_hook() -> None:
        execution_order.append("pre")

    def retry_hook(attempt: int) -> None:
        execution_order.append(f"retry-{attempt}")

    def do_work() -> str:
        nonlocal attempt_count
        attempt_count += 1
        execution_order.append(f"main-{attempt_count}")
        if attempt_count < 3:
            raise ValueError("retry me")
        return "success"

    hooks = Hooks(
        pre_hooks=[pre_hook],
        retry_hooks=[retry_hook],
        retry_config=RetryConfig(on=ValueError, attempts=5),
    )
    result = hooks.invoke(do_work)
    assert result == "success"
    assert attempt_count == 3
    # Pre runs once, then attempt 1, retry hook before attempt 2, retry hook before attempt 3
    assert execution_order == [
        "pre",
        "main-1",
        "retry-2",
        "main-2",
        "retry-3",
        "main-3",
    ]


def test_invoke_with_dataclass_context() -> None:
    """Test invoke with dataclass context instead of dict."""
    from dataclasses import dataclass

    @dataclass
    class ApiContext:
        method: str
        endpoint: str
        workspace: str

    captured_context: ApiContext | None = None

    def pre_hook(ctx: ApiContext) -> None:
        nonlocal captured_context
        captured_context = ctx

    def do_work(user_id: int) -> dict:
        return {"user_id": user_id, "name": "test"}

    context = ApiContext(method="GET", endpoint="/users", workspace="prod")
    hooks = Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG)
    result = hooks.with_context(context).invoke(do_work, 123)

    assert result == {"user_id": 123, "name": "test"}
    assert captured_context is not None
    assert captured_context.method == "GET"
    assert captured_context.endpoint == "/users"
    assert captured_context.workspace == "prod"


def test_invoke_multiple_hooks_composition() -> None:
    """Test invoke with multiple hooks of each type."""
    execution_order: list[str] = []

    def pre_hook1() -> None:
        execution_order.append("pre1")

    def pre_hook2() -> None:
        execution_order.append("pre2")

    def post_hook1() -> None:
        execution_order.append("post1")

    def post_hook2() -> None:
        execution_order.append("post2")

    def do_work() -> str:
        execution_order.append("main")
        return "result"

    hooks = Hooks(
        pre_hooks=[pre_hook1, pre_hook2],
        post_hooks=[post_hook1, post_hook2],
        retry_config=NO_RETRY_CONFIG,
    )
    result = hooks.invoke(do_work)

    assert result == "result"
    # Hooks execute in order
    assert execution_order == ["pre1", "pre2", "main", "post1", "post2"]
