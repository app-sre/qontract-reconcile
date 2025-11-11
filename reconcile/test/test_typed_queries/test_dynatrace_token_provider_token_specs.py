from collections.abc import (
    Callable,
    Mapping,
)
from typing import TYPE_CHECKING, cast

from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DEFINITION,
    DynatraceTokenProviderTokenSpecsQueryData,
)
from reconcile.typed_queries.dynatrace_token_provider_token_specs import (
    get_dynatrace_token_provider_token_specs,
)
from reconcile.utils.gql import GqlApi

if TYPE_CHECKING:
    from unittest.mock import MagicMock


def test_no_dynatrace_token_provider_token_specs(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecsQueryData],
) -> None:
    data = gql_class_factory(DynatraceTokenProviderTokenSpecsQueryData, {})
    api = gql_api_builder(data.model_dump(by_alias=True))
    envs = get_dynatrace_token_provider_token_specs(api=api)
    assert envs == []
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION)


def test_multiple_dynatrace_token_provider_token_specs(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., DynatraceTokenProviderTokenSpecsQueryData],
) -> None:
    data = gql_class_factory(
        DynatraceTokenProviderTokenSpecsQueryData,
        {
            "token_specs": [
                {"ocm_org_ids": [], "secrets": []},
                {"ocm_org_ids": [], "secrets": []},
            ]
        },
    )
    api = gql_api_builder(data.model_dump(by_alias=True))
    envs = get_dynatrace_token_provider_token_specs(api=api)
    assert envs == data.token_specs
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION)
