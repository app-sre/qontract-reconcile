"""Tests for @invoke_with_hooks on generator functions.

Covers generator-specific behavior: hooks fire around actual iteration,
not around generator object creation.
"""

from collections.abc import Generator, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from qontract_utils.hooks import NO_RETRY_CONFIG, Hooks, invoke_with_hooks, with_hooks


def test_generator_yields_correct_values() -> None:
    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def items(self) -> Iterator[int]:
            yield from [1, 2, 3]

    assert list(TestApi().items()) == [1, 2, 3]


def test_generator_pre_hooks_fire_on_iteration() -> None:
    """Pre-hooks must fire when iteration starts, not when the generator object is created."""
    execution_order: list[str] = []

    def pre_hook() -> None:
        execution_order.append("pre")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(pre_hooks=[pre_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def items(self) -> Iterator[int]:
            execution_order.append("yield")
            yield 1

    api = TestApi()
    gen = api.items()
    assert execution_order == []
    next(gen)
    assert execution_order == ["pre", "yield"]


def test_generator_post_hooks_fire_after_exhaustion() -> None:
    execution_order: list[str] = []

    def post_hook() -> None:
        execution_order.append("post")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(post_hooks=[post_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def items(self) -> Iterator[int]:
            yield 1
            execution_order.append("after_yield")

    api = TestApi()
    result = list(api.items())
    assert result == [1]
    assert execution_order == ["after_yield", "post"]


def test_generator_post_hooks_fire_on_close() -> None:
    """Post-hooks fire even if generator is closed before exhaustion."""
    execution_order: list[str] = []

    def post_hook() -> None:
        execution_order.append("post")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(post_hooks=[post_hook], retry_config=NO_RETRY_CONFIG)

        @invoke_with_hooks()
        def items(self) -> Generator[int, None, None]:
            yield 1
            yield 2
            yield 3

    api = TestApi()
    gen = api.items()
    next(gen)
    gen.close()
    assert "post" in execution_order


def test_generator_error_hooks_fire_on_exception() -> None:
    execution_order: list[str] = []

    def error_hook() -> None:
        execution_order.append("error")

    def post_hook() -> None:
        execution_order.append("post")

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                error_hooks=[error_hook],
                post_hooks=[post_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks()
        def items(self) -> Iterator[int]:
            yield 1
            raise ValueError("boom")

    api = TestApi()
    gen = api.items()
    next(gen)
    with pytest.raises(ValueError, match="boom"):
        next(gen)
    assert execution_order == ["error", "post"]


def test_generator_context_passed_to_hooks() -> None:
    @dataclass(frozen=True)
    class Ctx:
        method: str

    contexts: list[Any] = []

    def pre_hook(ctx: Ctx) -> None:
        contexts.append(("pre", ctx))

    def post_hook(ctx: Ctx) -> None:
        contexts.append(("post", ctx))

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[pre_hook],
                post_hooks=[post_hook],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks(lambda: Ctx(method="items"))
        def items(self) -> Iterator[int]:
            yield 1

    list(TestApi().items())
    assert len(contexts) == 2
    assert contexts[0] == ("pre", Ctx(method="items"))
    assert contexts[1] == ("post", Ctx(method="items"))


def test_generator_with_hooks_decorator() -> None:
    """Works with @with_hooks class decorator."""
    contexts: list[Any] = []

    def user_hook(ctx: Any) -> None:
        contexts.append(ctx)

    @dataclass(frozen=True)
    class Ctx:
        method: str

    default_hooks = Hooks(retry_config=NO_RETRY_CONFIG)

    @with_hooks(hooks=default_hooks)
    class TestApi:
        _hooks: Hooks

        def __init__(self, hooks: Hooks | None = None) -> None:
            pass

        @invoke_with_hooks(lambda: Ctx(method="items"))
        def items(self) -> Iterator[int]:
            yield from [10, 20]

    api = TestApi(hooks=Hooks(pre_hooks=[user_hook]))
    assert list(api.items()) == [10, 20]
    assert len(contexts) == 1
    assert contexts[0].method == "items"


def test_generator_hook_execution_order() -> None:
    execution_order: list[str] = []

    class TestApi:
        def __init__(self) -> None:
            self._hooks = Hooks(
                pre_hooks=[lambda: execution_order.append("pre")],
                post_hooks=[lambda: execution_order.append("post")],
                retry_config=NO_RETRY_CONFIG,
            )

        @invoke_with_hooks()
        def items(self) -> Iterator[str]:
            execution_order.append("yield_1")
            yield "a"
            execution_order.append("yield_2")
            yield "b"

    result = list(TestApi().items())
    assert result == ["a", "b"]
    assert execution_order == ["pre", "yield_1", "yield_2", "post"]
