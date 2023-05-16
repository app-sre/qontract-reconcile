from collections.abc import Callable

from reconcile.gql_definitions.openshift_service_account_tokens.openshift_service_account_tokens import (
    ServiceAccountTokensQueryData,
)
from reconcile.typed_queries.openshift_service_account_tokens import (
    get_openshift_service_account_tokens,
)
from reconcile.utils.gql import GqlApi


def test_no_data(
    gql_class_factory: Callable[..., ServiceAccountTokensQueryData],
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    data = gql_class_factory(ServiceAccountTokensQueryData, {})
    gql_api = gql_api_builder(data.dict(by_alias=True))
    result = get_openshift_service_account_tokens(gql_api)

    assert len(result) == 0
    gql_api.query.assert_called_once()


def test_get_openshift_service_account_tokens(
    gql_class_factory: Callable[..., ServiceAccountTokensQueryData],
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    data = gql_class_factory(
        ServiceAccountTokensQueryData,
        {
            "namespaces": [{"cluster": {}}],
        },
    )
    gql_api = gql_api_builder(data.dict(by_alias=True))
    result = get_openshift_service_account_tokens(gql_api)

    assert len(result) == 1
    gql_api.query.assert_called_once()
