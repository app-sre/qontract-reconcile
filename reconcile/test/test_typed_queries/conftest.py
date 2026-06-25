from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Mapping,
    )


@pytest.fixture
def query_func() -> Callable[[Mapping], Callable]:
    def builder(data: Mapping) -> Callable:
        def query_func(*args: Any, **kwargs: Any) -> Mapping:
            return data

        return query_func

    return builder
