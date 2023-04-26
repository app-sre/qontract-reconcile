from collections.abc import (
    Callable,
    Mapping,
)
from typing import (
    Any,
    Optional,
)
from unittest.mock import create_autospec

import pytest

from reconcile.utils.gql import GqlApi


@pytest.fixture
def query_func() -> Callable[[Mapping], Callable]:
    def builder(data: Mapping) -> Callable:
        def query_func(*args: Any, **kwargs: Any):
            return data

        return query_func

    return builder


@pytest.fixture
def gql_api_builder() -> Callable[[Optional[Mapping]], GqlApi]:
    def builder(data: Optional[Mapping] = None) -> GqlApi:
        gql_api = create_autospec(GqlApi)
        gql_api.query.return_value = data
        return gql_api

    return builder
