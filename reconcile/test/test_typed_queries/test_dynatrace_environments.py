from __future__ import annotations

from typing import TYPE_CHECKING, cast

from reconcile.gql_definitions.dynatrace_token_provider.dynatrace_bootstrap_tokens import (
    DEFINITION,
    DynatraceEnvironmentQueryData,
)
from reconcile.typed_queries.dynatrace_environments import get_dynatrace_environments

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Mapping,
    )
    from unittest.mock import MagicMock

    from reconcile.utils.gql import GqlApi


def test_no_dynatrace_environments(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., DynatraceEnvironmentQueryData],
) -> None:
    data = gql_class_factory(DynatraceEnvironmentQueryData, {})
    api = gql_api_builder(data.model_dump(by_alias=True))
    envs = get_dynatrace_environments(api=api)
    assert envs == []
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION)


def test_multiple_dynatrace_environments(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., DynatraceEnvironmentQueryData],
) -> None:
    data = gql_class_factory(
        DynatraceEnvironmentQueryData,
        {"environments": [{"bootstrapToken": {}}, {"bootstrapToken": {}}]},
    )
    api = gql_api_builder(data.model_dump(by_alias=True))
    envs = get_dynatrace_environments(api=api)
    assert envs == data.environments
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION)
