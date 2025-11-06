from collections.abc import Callable
from json import dumps
from unittest.mock import ANY

import pytest

from reconcile.gql_definitions.cost_report.cost_namespaces import (
    CostNamespacesQueryData,
)
from reconcile.typed_queries.cost_report.cost_namespaces import (
    CostNamespace,
    CostNamespaceLabels,
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
                    "labels": '{"insights_cost_management_optimizations":"true"}',
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
        labels=CostNamespaceLabels(insights_cost_management_optimizations="true"),
        app_name="a",
        cluster_name="c",
        cluster_external_id="id",
    )


def test_get_cost_namespaces(
    gql_api_builder: Callable[..., GqlApi],
    namespace_response: CostNamespacesQueryData,
    expected_cost_namespace: CostNamespace,
) -> None:
    response = namespace_response.model_dump(by_alias=True)
    # .dict will convert all nested fields to dicts, including labels
    # the mocked response need to be json string to match data type
    for n in response["namespaces"]:
        n["labels"] = dumps(n["labels"])
    gql_api = gql_api_builder(response)
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
    gql_api.query.assert_called_once_with(  # type: ignore[attr-defined]
        ANY,
        expected_vars,
    )
