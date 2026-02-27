"""Tests for @invoke_with_hooks on instance methods.

Covers the primary usage pattern: instance methods on classes with self._hooks.
Tests hook execution order, context handling, and error propagation.
"""

import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest
from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, invoke_with_hooks


def test_no_hooks() -> None:
    """Test context manager works without any hooks."""
    execution_log: list[str] = []

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks(lambda: {"value": 0})
        def do_work(self) -> None:
            execution_log.append("work")

    api = TestApi()
    api.do_work()
    assert execution_log == ["work"]


def test_pre_hook_execution() -> None:
    """Test pre-hooks are executed before the method."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["pre", "main"]


def test_multiple_pre_hooks() -> None:
    """Test multiple pre-hooks are executed in order."""
    execution_order: list[str] = []

    def pre_hook_1() -> None:
        execution_order.append("pre1")

    def pre_hook_2() -> None:
        execution_order.append("pre2")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook_1, pre_hook_2], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["pre1", "pre2", "main"]


def test_post_hook_execution() -> None:
    """Test post-hooks are executed after the method."""
    execution_order: list[str] = []

    def post_hook() -> None:
        execution_order.append("post")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(post_hooks=[post_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["main", "post"]


def test_multiple_post_hooks() -> None:
    """Test multiple post-hooks are executed in order."""
    execution_order: list[str] = []

    def post_hook_1() -> None:
        execution_order.append("post1")

    def post_hook_2() -> None:
        execution_order.append("post2")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                post_hooks=[post_hook_1, post_hook_2], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["main", "post1", "post2"]


def test_error_hook_on_exception() -> None:
    """Test error-hooks are executed when an exception occurs."""
    execution_order: list[str] = []

    def error_hook() -> None:
        execution_order.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(error_hooks=[error_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")
            raise ValueError("test error")

    api = TestApi()
    with pytest.raises(ValueError, match="test error"):
        api.do_work()

    assert execution_order == ["main", "error"]


def test_multiple_error_hooks() -> None:
    """Test multiple error-hooks are executed in order."""
    execution_order: list[str] = []

    def error_hook_1() -> None:
        execution_order.append("error1")

    def error_hook_2() -> None:
        execution_order.append("error2")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                error_hooks=[error_hook_1, error_hook_2], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")
            raise ValueError("test error")

    api = TestApi()
    with pytest.raises(ValueError, match="test error"):
        api.do_work()

    assert execution_order == ["main", "error1", "error2"]


def test_error_hooks_not_called_on_success() -> None:
    """Test error-hooks are NOT executed when no exception occurs."""
    execution_order: list[str] = []

    def error_hook() -> None:
        execution_order.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(error_hooks=[error_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["main"]


def test_post_hooks_called_after_error_hooks() -> None:
    """Test post-hooks are executed after error-hooks."""
    execution_order: list[str] = []

    def error_hook() -> None:
        execution_order.append("error")

    def post_hook() -> None:
        execution_order.append("post")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                post_hooks=[post_hook],
                error_hooks=[error_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")
            raise ValueError("test error")

    api = TestApi()
    with pytest.raises(ValueError, match="test error"):
        api.do_work()

    assert execution_order == ["main", "error", "post"]


def test_full_lifecycle_no_error() -> None:
    """Test all hooks execute in correct order without errors."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    def post_hook() -> None:
        execution_order.append("post")

    def error_hook() -> None:
        execution_order.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                error_hooks=[error_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["pre", "main", "post"]


def test_full_lifecycle_with_error() -> None:
    """Test all hooks execute in correct order with errors."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    def post_hook() -> None:
        execution_order.append("post")

    def error_hook() -> None:
        execution_order.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                error_hooks=[error_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            execution_order.append("main")
            raise ValueError("test error")

    api = TestApi()
    with pytest.raises(ValueError, match="test error"):
        api.do_work()

    assert execution_order == ["pre", "main", "error", "post"]


def test_context_modification_in_pre_hook() -> None:
    """Test pre-hooks can modify context."""
    context_data: dict[str, Any] = {}

    def pre_hook(ctx: dict[str, Any]) -> None:
        ctx["modified"] = True

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks(lambda: context_data)
        def do_work(self) -> None:
            pass

    api = TestApi()
    api.do_work()
    assert context_data["modified"] is True


def test_context_modification_in_post_hook() -> None:
    """Test post-hooks can access modified context."""
    context_data: dict[str, Any] = {}

    def post_hook(ctx: dict[str, Any]) -> None:
        ctx["final_value"] = ctx.get("value", 0) * 2
        # Store context for verification
        context_data.update(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(post_hooks=[post_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks(lambda: {"value": 21})
        def do_work(self) -> None:
            pass

    api = TestApi()
    api.do_work()
    assert context_data["final_value"] == 42


def test_context_modification_in_error_hook() -> None:
    """Test error-hooks can access context during error."""
    context_data: dict[str, Any] = {}

    def error_hook(ctx: dict[str, Any]) -> None:
        ctx["error_handled"] = True
        # Store context for verification
        context_data.update(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(error_hooks=[error_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks(lambda: context_data)
        def do_work(self) -> None:
            raise ValueError("test error")

    api = TestApi()
    with pytest.raises(ValueError, match="test error"):
        api.do_work()

    assert context_data["error_handled"] is True


def test_exception_propagation() -> None:
    """Test exceptions are properly propagated."""

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            raise RuntimeError("custom error")

    api = TestApi()
    with pytest.raises(RuntimeError, match="custom error"):
        api.do_work()


def test_exception_in_pre_hook() -> None:
    """Test exceptions in pre-hooks are propagated."""

    def pre_hook() -> None:
        raise ValueError("pre-hook error")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            pass

    api = TestApi()
    with pytest.raises(ValueError, match="pre-hook error"):
        api.do_work()


def test_exception_in_post_hook() -> None:
    """Test exceptions in post-hooks are propagated."""

    def post_hook() -> None:
        raise ValueError("post-hook error")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(post_hooks=[post_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            pass

    api = TestApi()
    with pytest.raises(ValueError, match="post-hook error"):
        api.do_work()


def test_exception_in_error_hook() -> None:
    """Test exceptions in error-hooks are propagated (last one wins)."""

    def error_hook() -> None:
        raise ValueError("error-hook error")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(error_hooks=[error_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            raise RuntimeError("original error")

    api = TestApi()
    with pytest.raises(ValueError, match="error-hook error"):
        api.do_work()


def test_typed_context() -> None:
    """Test with typed context objects."""

    class MyContext:
        def __init__(self) -> None:
            self.value = 0

    def pre_hook(ctx: MyContext) -> None:
        ctx.value = 10

    def post_hook(ctx: MyContext) -> None:
        ctx.value *= 2

    shared_context = MyContext()

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks(lambda: shared_context)
        def do_work(self) -> None:
            shared_context.value += 5

    api = TestApi()
    api.do_work()
    assert shared_context.value == 30


def test_empty_hook_lists() -> None:
    """Test with explicitly empty hook lists."""

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks(lambda: {"value": 42})
        def do_work(self) -> int:
            return 42

    api = TestApi()
    result = api.do_work()
    assert result == 42


def test_post_hook_executes_even_after_main_error() -> None:
    """Test post-hooks are called even when main block raises."""
    post_hook_called: list[bool] = []

    def post_hook() -> None:
        post_hook_called.append(True)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(post_hooks=[post_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def do_work(self) -> None:
            raise ValueError("error in main")

    api = TestApi()
    with pytest.raises(ValueError, match="error in main"):
        api.do_work()

    assert post_hook_called == [True]


def test_exception_in_first_error_hook_stops_processing() -> None:
    """Test when first error hook raises, it stops processing other error hooks."""

    def error_hook_1() -> None:
        raise ValueError("error1")

    context_data: dict[str, Any] = {}

    def error_hook_2(ctx: dict[str, Any]) -> None:
        ctx["hook2_called"] = True
        context_data.update(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                error_hooks=[error_hook_1, error_hook_2], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks()
        def do_work(self) -> None:
            raise RuntimeError("original")

    api = TestApi()
    with pytest.raises(ValueError, match="error1"):
        api.do_work()

    # error_hook_2 should not be called because error_hook_1 raised
    assert "hook2_called" not in context_data


def test_context_state_preserved_across_hooks() -> None:
    """Test context state is preserved and accessible across all hooks."""
    execution_log: list[str] = []
    shared_context: dict[str, Any] = {}

    def pre_hook(ctx: dict[str, Any]) -> None:
        ctx["counter"] = 0
        execution_log.append(f"pre: {ctx['counter']}")

    def post_hook(ctx: dict[str, Any]) -> None:
        execution_log.append(f"post: {ctx['counter']}")
        # Store for verification
        shared_context.update(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks(lambda: shared_context)
        def do_work(self) -> None:
            shared_context["counter"] += 10
            execution_log.append(f"main: {shared_context['counter']}")

    api = TestApi()
    api.do_work()
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

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks(lambda: context)
        def do_work(self) -> None:
            pass

    api = TestApi()
    api.do_work()
    assert context.status == "completed"

    context2 = RequestContext(request_id="456")

    class TestApi2:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                error_hooks=[error_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks(lambda: context2)
        def do_work(self) -> None:
            raise ValueError("error")

    api2 = TestApi2()
    with pytest.raises(ValueError, match="error"):
        api2.do_work()

    assert context2.status == "completed"  # post_hook runs after error_hook


def _run_mypy(code: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run mypy --strict on a code snippet via temp file."""
    test_file = tmp_path / "test_snippet.py"
    test_file.write_text(textwrap.dedent(code))
    return subprocess.run(  # noqa: S603
        ["uv", "run", "mypy", "--strict", str(test_file)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )


def test_mypy_return_type_preserved(tmp_path: Path) -> None:
    """Test that mypy correctly infers return types through @invoke_with_hooks."""
    result = _run_mypy(
        """\
        from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, invoke_with_hooks

        class Api:
            def __init__(self) -> None:
                self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

            @invoke_with_hooks(lambda: {})
            def get_name(self) -> str:
                return "alice"

        api = Api()
        name: str = api.get_name()
    """,
        tmp_path,
    )
    assert result.returncode == 0, result.stdout


def test_mypy_return_type_mismatch_detected(tmp_path: Path) -> None:
    """Test that mypy catches return type mismatches through @invoke_with_hooks."""
    result = _run_mypy(
        """\
        from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, invoke_with_hooks

        class Api:
            def __init__(self) -> None:
                self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

            @invoke_with_hooks(lambda: {})
            def get_name(self) -> str:
                return "alice"

        api = Api()
        name: int = api.get_name()
    """,
        tmp_path,
    )
    assert result.returncode != 0
    assert "incompatible type" in result.stdout.lower()
