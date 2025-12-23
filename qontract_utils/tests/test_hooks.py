# ruff: noqa: SIM117 - for readability in tests
from typing import Any

import pytest
from qontract_utils.hooks import invoke_with_hooks


def test_no_hooks() -> None:
    """Test context manager works without any hooks."""
    context: dict[str, int] = {"value": 0}
    with invoke_with_hooks(context):
        context["value"] = 42
    assert context["value"] == 42


def test_pre_hook_execution() -> None:
    """Test pre-hooks are executed before the context block."""
    execution_order: list[str] = []

    def pre_hook(_ctx: Any) -> None:
        execution_order.append("pre")

    context: dict[str, Any] = {}
    with invoke_with_hooks(context, pre_hooks=[pre_hook]):
        execution_order.append("main")

    assert execution_order == ["pre", "main"]


def test_multiple_pre_hooks() -> None:
    """Test multiple pre-hooks are executed in order."""
    execution_order: list[str] = []

    def pre_hook_1(_ctx: Any) -> None:
        execution_order.append("pre1")

    def pre_hook_2(_ctx: Any) -> None:
        execution_order.append("pre2")

    context: dict[str, Any] = {}
    with invoke_with_hooks(context, pre_hooks=[pre_hook_1, pre_hook_2]):
        execution_order.append("main")

    assert execution_order == ["pre1", "pre2", "main"]


def test_post_hook_execution() -> None:
    """Test post-hooks are executed after the context block."""
    execution_order: list[str] = []

    def post_hook(_ctx: Any) -> None:
        execution_order.append("post")

    context: dict[str, Any] = {}
    with invoke_with_hooks(context, post_hooks=[post_hook]):
        execution_order.append("main")

    assert execution_order == ["main", "post"]


def test_multiple_post_hooks() -> None:
    """Test multiple post-hooks are executed in order."""
    execution_order: list[str] = []

    def post_hook_1(_ctx: Any) -> None:
        execution_order.append("post1")

    def post_hook_2(_ctx: Any) -> None:
        execution_order.append("post2")

    context: dict[str, Any] = {}
    with invoke_with_hooks(context, post_hooks=[post_hook_1, post_hook_2]):
        execution_order.append("main")

    assert execution_order == ["main", "post1", "post2"]


def test_error_hook_on_exception() -> None:
    """Test error-hooks are executed when an exception occurs."""
    execution_order: list[str] = []

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="test error"):
        with invoke_with_hooks(context, error_hooks=[error_hook]):
            execution_order.append("main")
            raise ValueError("test error")

    assert execution_order == ["main", "error"]


def test_multiple_error_hooks() -> None:
    """Test multiple error-hooks are executed in order."""
    execution_order: list[str] = []

    def error_hook_1(_ctx: Any) -> None:
        execution_order.append("error1")

    def error_hook_2(_ctx: Any) -> None:
        execution_order.append("error2")

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="test error"):
        with invoke_with_hooks(context, error_hooks=[error_hook_1, error_hook_2]):
            execution_order.append("main")
            raise ValueError("test error")

    assert execution_order == ["main", "error1", "error2"]


def test_error_hooks_not_called_on_success() -> None:
    """Test error-hooks are NOT executed when no exception occurs."""
    execution_order: list[str] = []

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    context: dict[str, Any] = {}
    with invoke_with_hooks(context, error_hooks=[error_hook]):
        execution_order.append("main")

    assert execution_order == ["main"]


def test_post_hooks_called_after_error_hooks() -> None:
    """Test post-hooks are executed after error-hooks."""
    execution_order: list[str] = []

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    def post_hook(_ctx: Any) -> None:
        execution_order.append("post")

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="test error"):
        with invoke_with_hooks(
            context, post_hooks=[post_hook], error_hooks=[error_hook]
        ):
            execution_order.append("main")
            raise ValueError("test error")

    assert execution_order == ["main", "error", "post"]


def test_full_lifecycle_no_error() -> None:
    """Test all hooks execute in correct order without errors."""
    execution_order: list[str] = []

    def pre_hook(_ctx: Any) -> None:
        execution_order.append("pre")

    def post_hook(_ctx: Any) -> None:
        execution_order.append("post")

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    context: dict[str, Any] = {}
    with invoke_with_hooks(
        context,
        pre_hooks=[pre_hook],
        post_hooks=[post_hook],
        error_hooks=[error_hook],
    ):
        execution_order.append("main")

    assert execution_order == ["pre", "main", "post"]


def test_full_lifecycle_with_error() -> None:
    """Test all hooks execute in correct order with errors."""
    execution_order: list[str] = []

    def pre_hook(_ctx: Any) -> None:
        execution_order.append("pre")

    def post_hook(_ctx: Any) -> None:
        execution_order.append("post")

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="test error"):
        with invoke_with_hooks(
            context,
            pre_hooks=[pre_hook],
            post_hooks=[post_hook],
            error_hooks=[error_hook],
        ):
            execution_order.append("main")
            raise ValueError("test error")

    assert execution_order == ["pre", "main", "error", "post"]


def test_context_modification_in_pre_hook() -> None:
    """Test pre-hooks can modify context."""

    def pre_hook(ctx: dict[str, Any]) -> None:
        ctx["modified"] = True

    context: dict[str, Any] = {}
    with invoke_with_hooks(context, pre_hooks=[pre_hook]):
        assert context["modified"] is True


def test_context_modification_in_post_hook() -> None:
    """Test post-hooks can access modified context."""

    def post_hook(ctx: dict[str, Any]) -> None:
        ctx["final_value"] = ctx["value"] * 2

    context: dict[str, Any] = {"value": 21}
    with invoke_with_hooks(context, post_hooks=[post_hook]):
        pass

    assert context["final_value"] == 42


def test_context_modification_in_error_hook() -> None:
    """Test error-hooks can access context during error."""

    def error_hook(ctx: dict[str, Any]) -> None:
        ctx["error_handled"] = True

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="test error"):
        with invoke_with_hooks(context, error_hooks=[error_hook]):
            raise ValueError("test error")

    assert context["error_handled"] is True


def test_exception_propagation() -> None:
    """Test exceptions are properly propagated."""
    context: dict[str, Any] = {}
    with pytest.raises(RuntimeError, match="custom error"):
        with invoke_with_hooks(context):
            raise RuntimeError("custom error")


def test_exception_in_pre_hook() -> None:
    """Test exceptions in pre-hooks are propagated."""

    def pre_hook(_ctx: Any) -> None:
        raise ValueError("pre-hook error")

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="pre-hook error"):
        with invoke_with_hooks(context, pre_hooks=[pre_hook]):
            pass


def test_exception_in_post_hook() -> None:
    """Test exceptions in post-hooks are propagated."""

    def post_hook(_ctx: Any) -> None:
        raise ValueError("post-hook error")

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="post-hook error"):
        with invoke_with_hooks(context, post_hooks=[post_hook]):
            pass


def test_exception_in_error_hook() -> None:
    """Test exceptions in error-hooks are propagated (last one wins)."""

    def error_hook(_ctx: Any) -> None:
        raise ValueError("error-hook error")

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="error-hook error"):
        with invoke_with_hooks(context, error_hooks=[error_hook]):
            raise RuntimeError("original error")


def test_typed_context() -> None:
    """Test with typed context objects."""

    class MyContext:
        def __init__(self) -> None:
            self.value = 0

    def pre_hook(ctx: MyContext) -> None:
        ctx.value = 10

    def post_hook(ctx: MyContext) -> None:
        ctx.value *= 2

    context = MyContext()
    with invoke_with_hooks(context, pre_hooks=[pre_hook], post_hooks=[post_hook]):
        context.value += 5

    assert context.value == 30


def test_empty_hook_lists() -> None:
    """Test with explicitly empty hook lists."""
    context: dict[str, int] = {"value": 42}
    with invoke_with_hooks(context, pre_hooks=[], post_hooks=[], error_hooks=[]):
        pass
    assert context["value"] == 42


def test_none_hook_lists() -> None:
    """Test with None hook lists (default behavior)."""
    context: dict[str, int] = {"value": 42}
    with invoke_with_hooks(context, pre_hooks=None, post_hooks=None, error_hooks=None):
        pass
    assert context["value"] == 42


def test_post_hook_executes_even_after_main_error() -> None:
    """Test post-hooks are called even when main block raises."""
    post_hook_called: list[bool] = []

    def post_hook(_ctx: Any) -> None:
        post_hook_called.append(True)

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="error in main"):
        with invoke_with_hooks(context, post_hooks=[post_hook]):
            raise ValueError("error in main")

    assert post_hook_called == [True]


def test_exception_in_first_error_hook_stops_processing() -> None:
    """Test when first error hook raises, it stops processing other error hooks."""

    def error_hook_1(_ctx: Any) -> None:
        raise ValueError("error1")

    def error_hook_2(ctx: dict[str, Any]) -> None:
        ctx["hook2_called"] = True

    context: dict[str, Any] = {}
    with pytest.raises(ValueError, match="error1"):
        with invoke_with_hooks(context, error_hooks=[error_hook_1, error_hook_2]):
            raise RuntimeError("original")

    # error_hook_2 should not be called because error_hook_1 raised
    assert "hook2_called" not in context


def test_context_state_preserved_across_hooks() -> None:
    """Test context state is preserved and accessible across all hooks."""
    execution_log: list[str] = []

    def pre_hook(ctx: dict[str, Any]) -> None:
        ctx["counter"] = 0
        execution_log.append(f"pre: {ctx['counter']}")

    def post_hook(ctx: dict[str, Any]) -> None:
        execution_log.append(f"post: {ctx['counter']}")

    context: dict[str, Any] = {}
    with invoke_with_hooks(context, pre_hooks=[pre_hook], post_hooks=[post_hook]):
        context["counter"] += 10
        execution_log.append(f"main: {context['counter']}")

    assert execution_log == ["pre: 0", "main: 10", "post: 10"]


def test_complex_context_type() -> None:
    """Test with complex context types like dataclasses."""
    from dataclasses import dataclass

    @dataclass
    class RequestContext:
        request_id: str
        status: str = "pending"

    def pre_hook(ctx: RequestContext) -> None:
        ctx.status = "processing"

    def post_hook(ctx: RequestContext) -> None:
        ctx.status = "completed"

    def error_hook(ctx: RequestContext) -> None:
        ctx.status = "failed"

    context = RequestContext(request_id="123")
    with invoke_with_hooks(context, pre_hooks=[pre_hook], post_hooks=[post_hook]):
        pass

    assert context.status == "completed"

    context2 = RequestContext(request_id="456")
    with pytest.raises(ValueError, match="error"):
        with invoke_with_hooks(
            context2,
            pre_hooks=[pre_hook],
            post_hooks=[post_hook],
            error_hooks=[error_hook],
        ):
            raise ValueError("error")

    assert context2.status == "completed"  # post_hook runs after error_hook
