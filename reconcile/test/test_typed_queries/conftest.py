from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

import pytest


@pytest.fixture
def query_func() -> Callable[[Mapping], Callable]:
    def builder(data: Mapping) -> Callable:
        def query_func(*args: Any, **kwargs: Any):
            return data

        return query_func

    return builder
