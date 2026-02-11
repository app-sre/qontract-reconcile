"""Tests for @invoke_with_hooks on standalone functions and static methods.

Covers the decorator pattern for functions that are not instance methods,
including standalone functions, class static methods, and the error case
of calling without hooks.
"""

from typing import Any

import pytest

# ruff: noqa: ARG001
from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, RetryConfig, invoke_with_hooks


def test_standalone_function() -> None:
    """Test execution of standalone function decorated with invoke_with_hooks."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    @invoke_with_hooks(hooks=Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG))
    def do_work(*args: Any, **kwargs: Any) -> str:
        assert args == ("arg1", "arg2")
        assert kwargs == {"kwarg1": "value1", "kwarg2": "value2"}
        execution_order.append("main")
        return "result"

    r = do_work("arg1", "arg2", kwarg1="value1", kwarg2="value2")
    assert r == "result"
    assert execution_order == ["pre", "main"]


def test_standalone_function_with_all_hooks() -> None:
    """Test standalone function with all hook types."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    def post_hook() -> None:
        execution_order.append("post")

    def error_hook() -> None:
        execution_order.append("error")

    @invoke_with_hooks(
        hooks=Hooks(
            pre_hooks=[pre_hook],
            post_hooks=[post_hook],
            error_hooks=[error_hook],
            retry_config=NO_RETRY_CONFIG,
        )
    )
    def do_work_success() -> str:
        execution_order.append("main")
        return "success"

    result = do_work_success()
    assert result == "success"
    assert execution_order == ["pre", "main", "post"]

    # Reset and test error case
    execution_order.clear()

    @invoke_with_hooks(
        hooks=Hooks(
            pre_hooks=[pre_hook],
            post_hooks=[post_hook],
            error_hooks=[error_hook],
            retry_config=NO_RETRY_CONFIG,
        )
    )
    def do_work_error() -> None:
        execution_order.append("main")
        raise ValueError("test error")

    with pytest.raises(ValueError, match="test error"):
        do_work_error()

    assert execution_order == ["pre", "main", "error", "post"]


def test_standalone_function_with_context() -> None:
    """Test standalone function with context factory."""
    from dataclasses import dataclass

    @dataclass
    class MyContext:
        value: int

    captured_context: MyContext | None = None

    def pre_hook(ctx: MyContext) -> None:
        nonlocal captured_context
        captured_context = ctx

    @invoke_with_hooks(
        context_factory=lambda: MyContext(value=42),
        hooks=Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG),
    )
    def do_work(x: int) -> int:
        return x * 2

    result = do_work(10)
    assert result == 20
    assert captured_context is not None
    assert captured_context.value == 42


def test_standalone_function_with_retry(enable_retry: None) -> None:
    """Test standalone function with retry support."""
    execution_order: list[str] = []
    attempt_count = 0

    def retry_hook(attempt: int) -> None:
        execution_order.append(f"retry-{attempt}")

    @invoke_with_hooks(
        hooks=Hooks(
            retry_hooks=[retry_hook],
            retry_config=RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            ),
        )
    )
    def do_work_with_retry() -> str:
        nonlocal attempt_count
        attempt_count += 1
        execution_order.append(f"main-{attempt_count}")
        if attempt_count < 3:
            raise ValueError("retry me")
        return "success"

    result = do_work_with_retry()
    assert result == "success"
    assert attempt_count == 3
    assert execution_order == ["main-1", "retry-2", "main-2", "retry-3", "main-3"]


def test_standalone_function_without_hooks_fails() -> None:
    """Test that calling decorated standalone function without hooks parameter fails."""

    @invoke_with_hooks()
    def do_work() -> str:
        return "result"

    with pytest.raises(
        ValueError,
        match="Cannot call decorated function directly without hooks parameter",
    ):
        do_work()


def test_class_static_method() -> None:
    """Test decorator on actual @staticmethod in a class."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    class MyClass:
        @staticmethod
        @invoke_with_hooks(
            hooks=Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG)
        )
        def static_work(x: int) -> int:
            execution_order.append("main")
            return x * 2

    result = MyClass.static_work(21)
    assert result == 42
    assert execution_order == ["pre", "main"]

    # Also test calling via instance
    execution_order.clear()
    instance = MyClass()
    result = instance.static_work(21)
    assert result == 42
    assert execution_order == ["pre", "main"]
