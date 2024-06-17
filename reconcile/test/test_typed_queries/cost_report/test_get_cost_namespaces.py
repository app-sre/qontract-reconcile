from collections.abc import Callable
from unittest.mock import ANY

import pytest

from reconcile.gql_definitions.cost_report.cost_namespaces import (
    CostNamespacesQueryData,
)
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    get_cost_namespaces,
)
from reconcile.utils.gql import GqlApi


def test_get_cost_namespaces_when_no_data(
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    gql_api = gql_api_builder({"namespaces": None})

    apps = get_cost_namespaces(gql_api)

    assert apps == []


@pytest.fixture
def namespace_response(
    gql_class_factory: Callable[..., CostNamespacesQueryData],
) -> CostNamespacesQueryData:
    return gql_class_factory(
        CostNamespacesQueryData,
        {
            "namespaces": [
                {
                    "name": "n",
                    "app": {"name": "a"},
                    "cluster": {
                        "name": "c",
                        "spec": {"external_id": "id"},
                    },
                }
            ],
        },
    )


@pytest.fixture
def expected_cost_namespace() -> CostNamespace:
    return CostNamespace(
        name="n",
        app_name="a",
        cluster_name="c",
        cluster_external_id="id",
    )


def test_get_cost_namespaces(
    gql_api_builder: Callable[..., GqlApi],
    namespace_response: CostNamespacesQueryData,
    expected_cost_namespace: CostNamespace,
) -> None:
    gql_api = gql_api_builder(namespace_response.dict(by_alias=True))
    expected_vars = {
        "filter": {
            "cluster": {
                "filter": {
                    "enableCostReport": True,
                },
            },
        },
    }

    namespaces = get_cost_namespaces(gql_api)

    assert namespaces == [expected_cost_namespace]
    gql_api.query.assert_called_once_with(
        ANY,
        expected_vars,
    )
