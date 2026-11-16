from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from graphql import build_client_schema, graphql_sync

from reconcile import queries
from reconcile.typed_queries import external_resources
from reconcile.utils.oc import OC_Map

if TYPE_CHECKING:
    from collections.abc import Callable

    from graphql import GraphQLSchema
    from pytest_mock import MockerFixture


@pytest.fixture(scope="module")
def graphql_schema() -> GraphQLSchema:
    introspection = Path(__file__).parents[1] / "gql_definitions" / "introspection.json"
    return build_client_schema(json.loads(introspection.read_text())["data"])


@pytest.fixture
def namespace() -> dict[str, Any]:
    return {
        "path": "/namespaces/test.yml",
        "name": "test-namespace",
        "environment": {
            "name": "stage",
            "labels": "{}",
            "parameters": '{"PARAMETER":"value"}',
            "servicePhase": "stage",
        },
        "app": {
            "path": "/apps/test.yml",
            "name": "test-app",
            "appCode": "test",
            "costCenter": "test",
        },
        "cluster": {
            "name": "test-cluster",
            "serverUrl": "https://api.example.com",
            "internal": True,
        },
    }


@pytest.fixture
def query_backend(
    mocker: MockerFixture, graphql_schema: GraphQLSchema, namespace: dict[str, Any]
) -> dict[str, Any]:
    root = {
        "namespaces_v1": [namespace],
        "integrations_v1": [
            {"name": "test", "managed": [{"namespace": namespace, "spec": {}}]}
        ],
        "app_interface_sql_queries_v1": [
            {
                "path": "/sql-queries/test.yml",
                "name": "test-query",
                "namespace": namespace,
                "identifier": "test-db",
                "output": "stdout",
                "query": "SELECT 1;",
            }
        ],
    }

    def execute(query: str) -> dict[str, Any]:
        result = graphql_sync(graphql_schema, query, root_value=root)
        assert not result.errors, result.errors
        assert result.data is not None
        return result.data

    mocker.patch("reconcile.utils.gql.get_api").return_value.query.side_effect = execute
    return root


def fetch_cluster(source: str) -> dict[str, Any]:
    match source:
        case "managed-integrations":
            return queries.get_integrations(managed=True)[0]["managed"][0]["namespace"][
                "cluster"
            ]
        case "minimal-namespaces":
            return queries.get_namespaces(minimal=True)[0]["cluster"]
        case "sql-queries":
            return queries.get_app_interface_sql_queries()[0]["namespace"]["cluster"]
        case "external-resources":
            return external_resources.get_namespaces()[0].cluster.model_dump(
                by_alias=True
            )
        case _:
            raise ValueError(source)


@pytest.mark.parametrize(
    ("source", "privileged"),
    [
        ("managed-integrations", False),
        ("minimal-namespaces", False),
        ("sql-queries", False),
        ("external-resources", False),
        ("minimal-namespaces", True),
        ("external-resources", True),
    ],
)
@pytest.mark.parametrize(
    ("list_token", "legacy_token", "expected_path"),
    [
        (True, False, "tokens/active"),
        (True, True, "tokens/active"),
        (False, True, "tokens/legacy"),
    ],
)
def test_cluster_queries_connect_with_rotation_tokens(
    mocker: MockerFixture,
    query_backend: dict[str, Any],
    namespace: dict[str, Any],
    source: str,
    privileged: bool,
    list_token: bool,
    legacy_token: bool,
    expected_path: str,
) -> None:
    token_field = "clusterAdminAutomationToken" if privileged else "automationToken"
    namespace["cluster"][token_field] = (
        {"path": "tokens/legacy", "field": "token"} if legacy_token else None
    )
    namespace["cluster"][f"{token_field}s"] = [
        {
            "name": name,
            "namespace": "dedicated-admin",
            "active": active,
            "delete": delete,
            "secret": {"path": f"tokens/{name}", "field": "token"} if secret else None,
        }
        for name, active, delete, secret in [
            ("inactive", False, False, True),
            ("deleted", True, True, True),
            ("pending", True, False, False),
            ("active", list_token, False, True),
        ]
    ]
    secret_reader = mocker.Mock()
    secret_reader.read_all.return_value = {
        "server": "https://api.example.com",
        "token": "test-token",
    }
    oc = mocker.patch("reconcile.utils.oc.OC", autospec=True)

    with OC_Map(
        clusters=[fetch_cluster(source)],
        cluster_admin=privileged,
        secret_reader=secret_reader,
    ) as oc_map:
        assert (
            oc_map.get_cluster("test-cluster", privileged=privileged) is oc.return_value
        )

    secret_reader.read_all.assert_called_once()
    assert secret_reader.read_all.call_args.args[0]["path"] == expected_path
    assert oc.call_args.args[:3] == (
        "test-cluster",
        "https://api.example.com",
        "test-token",
    )


def test_sql_query_preserves_json_overrides(
    query_backend: dict[str, Any], namespace: dict[str, Any]
) -> None:
    namespace["externalResources"] = [
        {
            "__typename": "NamespaceTerraformProviderResourceAWS_v1",
            "provider": "aws",
            "provisioner": {"name": "test-account"},
            "resources": [
                {
                    "__typename": "NamespaceTerraformResourceRDS_v1",
                    "provider": "rds",
                    "identifier": "test-db",
                    "defaults": "/defaults/rds.yml",
                    "overrides": '{"engine":"postgres"}',
                }
            ],
        }
    ]

    sql_query = queries.get_app_interface_sql_queries()[0]
    overrides = sql_query["namespace"]["externalResources"][0]["resources"][0][
        "overrides"
    ]
    assert json.loads(overrides) == {"engine": "postgres"}


def test_managed_integrations_preserve_json_parameters(
    query_backend: dict[str, Any],
) -> None:
    integration = queries.get_integrations(managed=True)[0]
    parameters = integration["managed"][0]["namespace"]["environment"]["parameters"]
    assert json.loads(parameters) == {"PARAMETER": "value"}


@pytest.mark.parametrize(
    ("root_field", "fetch"),
    [
        ("integrations_v1", lambda: queries.get_integrations(managed=True)),
        ("namespaces_v1", lambda: queries.get_namespaces(minimal=True)),
        ("app_interface_sql_queries_v1", queries.get_app_interface_sql_queries),
    ],
)
@pytest.mark.parametrize("empty", [None, []])
def test_empty_cluster_queries(
    query_backend: dict[str, Any],
    root_field: str,
    fetch: Callable[[], list[dict[str, Any]]],
    empty: list | None,
) -> None:
    query_backend[root_field] = empty
    assert fetch() == []
