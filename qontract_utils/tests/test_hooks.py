from typing import Any

# ruff: noqa: ARG001
import pytest
import structlog
from qontract_utils.hooks import NO_RETRY_CONFIG, RetryConfig, invoke_with_hooks
from structlog.typing import EventDict


def test_no_hooks() -> None:
    """Test context manager works without any hooks."""
    execution_log: list[str] = []

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {"value": 0})
        def do_work(self) -> None:
            execution_log.append("work")

    api = TestApi()
    api.do_work()
    assert execution_log == ["work"]


def test_pre_hook_execution() -> None:
    """Test pre-hooks are executed before the method."""
    execution_order: list[str] = []

    def pre_hook(_ctx: Any) -> None:
        execution_order.append("pre")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["pre", "main"]


def test_multiple_pre_hooks() -> None:
    """Test multiple pre-hooks are executed in order."""
    execution_order: list[str] = []

    def pre_hook_1(_ctx: Any) -> None:
        execution_order.append("pre1")

    def pre_hook_2(_ctx: Any) -> None:
        execution_order.append("pre2")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook_1, pre_hook_2]
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["pre1", "pre2", "main"]


def test_post_hook_execution() -> None:
    """Test post-hooks are executed after the method."""
    execution_order: list[str] = []

    def post_hook(_ctx: Any) -> None:
        execution_order.append("post")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["main", "post"]


def test_multiple_post_hooks() -> None:
    """Test multiple post-hooks are executed in order."""
    execution_order: list[str] = []

    def post_hook_1(_ctx: Any) -> None:
        execution_order.append("post1")

    def post_hook_2(_ctx: Any) -> None:
        execution_order.append("post2")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook_1, post_hook_2]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["main", "post1", "post2"]


def test_error_hook_on_exception() -> None:
    """Test error-hooks are executed when an exception occurs."""
    execution_order: list[str] = []

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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

    def error_hook_1(_ctx: Any) -> None:
        execution_order.append("error1")

    def error_hook_2(_ctx: Any) -> None:
        execution_order.append("error2")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook_1, error_hook_2]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
    assert execution_order == ["main"]


def test_post_hooks_called_after_error_hooks() -> None:
    """Test post-hooks are executed after error-hooks."""
    execution_order: list[str] = []

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    def post_hook(_ctx: Any) -> None:
        execution_order.append("post")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook]
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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

    def pre_hook(_ctx: Any) -> None:
        execution_order.append("pre")

    def post_hook(_ctx: Any) -> None:
        execution_order.append("post")

    def error_hook(_ctx: Any) -> None:
        execution_order.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            execution_order.append("main")

    api = TestApi()
    api.do_work()
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

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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
        # Store context for verification
        context_data.update(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {"value": 21})
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
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            raise RuntimeError("custom error")

    api = TestApi()
    with pytest.raises(RuntimeError, match="custom error"):
        api.do_work()


def test_exception_in_pre_hook() -> None:
    """Test exceptions in pre-hooks are propagated."""

    def pre_hook(_ctx: Any) -> None:
        raise ValueError("pre-hook error")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            pass

    api = TestApi()
    with pytest.raises(ValueError, match="pre-hook error"):
        api.do_work()


def test_exception_in_post_hook() -> None:
    """Test exceptions in post-hooks are propagated."""

    def post_hook(_ctx: Any) -> None:
        raise ValueError("post-hook error")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            pass

    api = TestApi()
    with pytest.raises(ValueError, match="post-hook error"):
        api.do_work()


def test_exception_in_error_hook() -> None:
    """Test exceptions in error-hooks are propagated (last one wins)."""

    def error_hook(_ctx: Any) -> None:
        raise ValueError("error-hook error")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: shared_context)
        def do_work(self) -> None:
            shared_context.value += 5

    api = TestApi()
    api.do_work()
    assert shared_context.value == 30


def test_empty_hook_lists() -> None:
    """Test with explicitly empty hook lists."""

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {"value": 42})
        def do_work(self) -> int:
            return 42

    api = TestApi()
    result = api.do_work()
    assert result == 42


def test_post_hook_executes_even_after_main_error() -> None:
    """Test post-hooks are called even when main block raises."""
    post_hook_called: list[bool] = []

    def post_hook(_ctx: Any) -> None:
        post_hook_called.append(True)

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            raise ValueError("error in main")

    api = TestApi()
    with pytest.raises(ValueError, match="error in main"):
        api.do_work()

    assert post_hook_called == [True]


def test_exception_in_first_error_hook_stops_processing() -> None:
    """Test when first error hook raises, it stops processing other error hooks."""

    def error_hook_1(_ctx: Any) -> None:
        raise ValueError("error1")

    context_data: dict[str, Any] = {}

    def error_hook_2(ctx: dict[str, Any]) -> None:
        ctx["hook2_called"] = True
        context_data.update(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook_1, error_hook_2]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: {})
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
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: shared_context)
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
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: context)
        def do_work(self) -> None:
            pass

    api = TestApi()
    api.do_work()
    assert context.status == "completed"

    context2 = RequestContext(request_id="456")

    class TestApi2:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = NO_RETRY_CONFIG

        @invoke_with_hooks(lambda _self: context2)
        def do_work(self) -> None:
            raise ValueError("error")

    api2 = TestApi2()
    with pytest.raises(ValueError, match="error"):
        api2.do_work()

    assert context2.status == "completed"  # post_hook runs after error_hook


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
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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

    def retry_hook(_ctx: Any, attempt_num: int) -> None:
        retry_hook_calls.append(attempt_num)

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks = [retry_hook]
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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

    def pre_hook(_ctx: Any) -> None:
        pre_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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

    def post_hook(_ctx: Any) -> None:
        post_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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

    def post_hook(_ctx: Any) -> None:
        post_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks = [post_hook]
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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

    def error_hook(_ctx: Any) -> None:
        error_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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

    def error_hook(_ctx: Any) -> None:
        error_hook_calls["count"] += 1

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=3, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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

    def pre_hook(_ctx: Any) -> None:
        execution_log.append("pre")

    def post_hook(_ctx: Any) -> None:
        execution_log.append("post")

    def error_hook(_ctx: Any) -> None:
        execution_log.append("error")

    def retry_hook(_ctx: Any, attempt: int) -> None:
        execution_log.append(f"retry-{attempt}")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks = [error_hook]
            self._retry_hooks = [retry_hook]
            self._retry_config = RetryConfig(
                on=ValueError, attempts=4, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
        def do_work(self) -> None:
            execution_count["count"] += 1
            execution_log.append(f"main-{execution_count['count']}")
            if execution_count["count"] < 3:
                raise ValueError("retry")

    api = TestApi()
    api.do_work()
    # pre → main-1 → retry-2 → main-2 → retry-3 → main-3 → post
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
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {})
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
    """Test decorator retry_config parameter overrides instance._retry_config."""
    execution_count = {"count": 0}

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks: list[Any] = []
            self._post_hooks: list[Any] = []
            self._error_hooks: list[Any] = []
            self._retry_hooks: list[Any] = []
            # Instance has retry enabled
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        # Override: disable retry for this specific method
        @invoke_with_hooks(lambda _self: {}, retry_config=NO_RETRY_CONFIG)
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

    def pre_hook(_ctx: Any) -> None:
        execution_log.append("pre")

    def post_hook(_ctx: Any) -> None:
        execution_log.append("post")

    def error_hook(_ctx: Any) -> None:
        execution_log.append("error")

    class TestApi:
        def __init__(self) -> None:
            self._pre_hooks = [pre_hook]
            self._post_hooks = [post_hook]
            self._error_hooks = [error_hook]
            self._retry_hooks: list[Any] = []
            # Instance has retry enabled (but will be overridden)
            self._retry_config = RetryConfig(
                on=ValueError, attempts=5, wait_initial=0.001, wait_max=0.001
            )

        @invoke_with_hooks(lambda _self: {}, retry_config=NO_RETRY_CONFIG)
        def test_method(self) -> None:
            execution_log.append("main")
            raise ValueError("error")

    api = TestApi()
    with pytest.raises(ValueError, match="error"):
        api.test_method()

    # All hooks should run even with NO_RETRY_CONFIG
    assert execution_log == ["pre", "main", "error", "post"]
