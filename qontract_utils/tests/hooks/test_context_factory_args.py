"""Tests for context factory arg forwarding.

Tests cover all scenarios for context factories that declare method arguments
in their signature and receive those values at call time.
"""

# ruff: noqa: ARG001, ARG005 - self parameters in factories are part of the API being tested

import inspect
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest
from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, invoke_with_hooks


@dataclass(frozen=True)
class MyContext:
    """Test context dataclass for typed contexts."""

    path: str | None = None
    mount_point: str | None = None
    version: int | None = None


def test_factory_receives_method_args() -> None:
    """Test factory with method arg parameters receives actual arg values."""
    captured_context: list[MyContext] = []

    def capture_hook(ctx: MyContext) -> None:
        captured_context.append(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[capture_hook], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks(
            lambda self, path, mount_point: MyContext(
                path=path, mount_point=mount_point
            )
        )
        def do_work(self, path: str, mount_point: str) -> str:
            return f"{path}@{mount_point}"

    api = TestApi()
    result = api.do_work(path="secret/foo", mount_point="kv")

    assert result == "secret/foo@kv"
    assert len(captured_context) == 1
    assert captured_context[0].path == "secret/foo"
    assert captured_context[0].mount_point == "kv"


def test_factory_with_no_args() -> None:
    """Test factory with no args continues to work unchanged (backward compatibility)."""
    execution_log: list[str] = []

    def log_hook(ctx: dict[str, Any]) -> None:
        execution_log.append(f"hook: {ctx.get('static', False)}")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(pre_hooks=[log_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks(lambda: {"static": True})
        def do_work(self, path: str) -> str:
            execution_log.append("main")
            return path

    api = TestApi()
    result = api.do_work("secret/foo")

    assert result == "secret/foo"
    assert execution_log == ["hook: True", "main"]


def test_factory_with_self_only() -> None:
    """Test factory with self-only continues to work unchanged (backward compatibility)."""
    execution_log: list[str] = []

    def log_hook(ctx: dict[str, Any]) -> None:
        execution_log.append(f"hook: {ctx.get('id', 'none')}")

    class TestApi:
        def __init__(self, name: str) -> None:
            self.name = name
            self._hooks = Hooks(pre_hooks=[log_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks(lambda self: {"id": self.name})
        def do_work(self, path: str) -> str:
            execution_log.append("main")
            return path

    api = TestApi(name="test-api")
    result = api.do_work("secret/foo")

    assert result == "secret/foo"
    assert execution_log == ["hook: test-api", "main"]


def test_factory_receives_subset_of_args() -> None:
    """Test factory receives only the args it declares (not all method args)."""
    captured_context: list[MyContext] = []

    def capture_hook(ctx: MyContext) -> None:
        captured_context.append(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[capture_hook], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks(lambda self, path: MyContext(path=path))
        def do_work(self, path: str, mount_point: str, version: int) -> str:
            return f"{path}@{mount_point}:v{version}"

    api = TestApi()
    result = api.do_work(path="secret/foo", mount_point="kv", version=2)

    assert result == "secret/foo@kv:v2"
    assert len(captured_context) == 1
    assert captured_context[0].path == "secret/foo"
    assert captured_context[0].mount_point is None  # Not requested by factory
    assert captured_context[0].version is None  # Not requested by factory


def test_factory_receives_kwargs() -> None:
    """Test method called with keyword arguments - factory receives them correctly."""
    captured_context: list[MyContext] = []

    def capture_hook(ctx: MyContext) -> None:
        captured_context.append(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[capture_hook], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks(
            lambda self, path, mount_point: MyContext(
                path=path, mount_point=mount_point
            )
        )
        def do_work(self, path: str, mount_point: str) -> str:
            return f"{path}@{mount_point}"

    api = TestApi()
    result = api.do_work(path="secret/foo", mount_point="kv")

    assert result == "secret/foo@kv"
    assert len(captured_context) == 1
    assert captured_context[0].path == "secret/foo"
    assert captured_context[0].mount_point == "kv"


def test_factory_mismatch_raises_at_decoration_time() -> None:
    """Test factory declaring param not in method signature raises TypeError at decoration time."""
    with pytest.raises(
        TypeError,
        match="Context factory parameter 'nonexistent_param' not found in method 'do_work' signature",
    ):

        class TestApi:
            def __init__(self) -> None:
                self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

            @invoke_with_hooks(lambda self, nonexistent_param: {"value": nonexistent_param})
            def do_work(self, path: str) -> str:
                return path


def test_factory_signature_is_cached() -> None:
    """Test that signature inspection is cached per factory callable."""
    call_count = 0

    def factory(self: Any, path: str) -> dict[str, Any]:
        return {"path": path}

    # Patch inspect.signature to count calls
    with patch("qontract_utils.hooks.inspect.signature", wraps=inspect.signature) as mock_sig:  # type: ignore[name-defined]

        class TestApi:
            def __init__(self) -> None:
                self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

            @invoke_with_hooks(factory)
            def do_work(self, path: str) -> str:
                nonlocal call_count
                call_count += 1
                return path

        api = TestApi()

        # Call method multiple times
        api.do_work("secret/foo")
        api.do_work("secret/bar")
        api.do_work("secret/baz")

        assert call_count == 3

        # Signature should have been inspected only once for the factory
        # (Plus potentially for the wrapper function itself)
        factory_sig_calls = sum(
            1 for call in mock_sig.call_args_list if call[0][0] == factory
        )
        assert factory_sig_calls == 1


def test_factory_with_default_values_in_method() -> None:
    """Test factory receives default values when method is called without args."""
    captured_context: list[MyContext] = []

    def capture_hook(ctx: MyContext) -> None:
        captured_context.append(ctx)

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[capture_hook], retry_config=NO_RETRY_CONFIG
            )

        @invoke_with_hooks(lambda self, path: MyContext(path=path))
        def do_work(self, path: str = "default/path") -> str:
            return path

    api = TestApi()
    result = api.do_work()

    assert result == "default/path"
    assert len(captured_context) == 1
    assert captured_context[0].path == "default/path"


def test_factory_args_work_with_hooks() -> None:
    """Test full integration: factory with args, pre_hook and post_hook read context."""
    execution_log: list[str] = []

    def pre_hook(ctx: MyContext) -> None:
        execution_log.append(f"pre: {ctx.path}@{ctx.mount_point}")

    def post_hook(ctx: MyContext) -> None:
        execution_log.append(f"post: {ctx.path}@{ctx.mount_point}")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks(
            lambda self, path, mount_point: MyContext(
                path=path, mount_point=mount_point
            )
        )
        def do_work(self, path: str, mount_point: str) -> str:
            execution_log.append("main")
            return f"{path}@{mount_point}"

    api = TestApi()
    result = api.do_work(path="secret/foo", mount_point="kv")

    assert result == "secret/foo@kv"
    assert execution_log == [
        "pre: secret/foo@kv",
        "main",
        "post: secret/foo@kv",
    ]
