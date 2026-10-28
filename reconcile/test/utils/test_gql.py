from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import requests
from gql import Client, gql
from gql.transport.exceptions import TransportQueryError

if TYPE_CHECKING:
    from graphql import ExecutionResult
    from pytest_httpserver import HTTPServer
    from pytest_mock import MockerFixture

from reconcile.utils.gql import (
    GqlApi,
    GqlApiError,
    GqlApiErrorForbiddenSchemaError,
    GqlApiIntegrationNotFoundError,
    GqlGetResourceError,
    PersistentRequestsHTTPTransport,
)

TEST_QUERY = """
{
    integrations: integrations_v1 {
        name
        description
        schemas
    }
}
"""


def test_gqlapi_throws_gqlapierror_when_generic_exception_thrown(
    mocker: MockerFixture,
) -> None:
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = Exception("Something went wrong!")
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)  # type: ignore[attr-defined]


def test_gqlapi_throws_gqlapierror_when_connectionerror_exception_thrown(
    mocker: MockerFixture,
) -> None:
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = requests.exceptions.ConnectionError(
        "Could not connect with GraphQL API"
    )
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)  # type: ignore[attr-defined]


def test_gqlapi_throws_gqlapierror_when_transportqueryerror_exception_thrown(
    mocker: MockerFixture,
) -> None:
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = TransportQueryError("Error in GraphQL payload")
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)  # type: ignore[attr-defined]


def test_gqlapi_throws_gqlapierror_when_assertionerror_exception_thrown(
    mocker: MockerFixture,
) -> None:
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = AssertionError(
        "Transport returned an ExecutionResult without data or errors"
    )
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)  # type: ignore[attr-defined]


def test_gqlapi_throws_gqlapiintegrationnotfound_exception(
    mocker: MockerFixture,
) -> None:
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.return_value.formatted = {
        "data": {"integrations": [{"name": "INTEGRATION", "schemas": "TEST_SCHEMA"}]}
    }

    with pytest.raises(GqlApiIntegrationNotFoundError):
        gql_api = GqlApi(
            "test_url", "test_token", "INTEGRATION_NOT_FOUND", validate_schemas=True
        )
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)  # type: ignore[attr-defined]


def test_gqlapi_throws_gqlapierrorforbiddenschema_exception(
    mocker: MockerFixture,
) -> None:
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.return_value.formatted = {
        "data": {"integrations": [{"name": "INTEGRATION", "schemas": "TEST_SCHEMA"}]},
        "extensions": {"schemas": ["TEST_SCHEMA", "FORBIDDEN_TEST_SCHEMA"]},
    }

    with pytest.raises(GqlApiErrorForbiddenSchemaError):
        gql_api = GqlApi("test_url", "test_token", "INTEGRATION", validate_schemas=True)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)  # type: ignore[attr-defined]


# --- gql library integration tests (no mocking) ---

SIMPLE_QUERY = "{ __typename }"

GQL_RESPONSE = {"data": {"__typename": "Query"}}


@pytest.fixture
def graphql_server(httpserver: HTTPServer) -> HTTPServer:
    httpserver.expect_request("/graphql", method="POST").respond_with_json(GQL_RESPONSE)
    return httpserver


def test_persistent_transport_constructor(graphql_server: HTTPServer) -> None:
    session = requests.Session()
    transport = PersistentRequestsHTTPTransport(
        session,
        graphql_server.url_for("/graphql"),
        headers={"Authorization": "Basic test"},
        timeout=30,
    )
    assert transport.session is session
    assert transport.url == graphql_server.url_for("/graphql")


def test_persistent_transport_connect_close_are_noops() -> None:
    session = requests.Session()
    transport = PersistentRequestsHTTPTransport(session, "http://localhost/graphql")
    transport.connect()
    transport.close()
    assert not session.headers.get("_closed")


def test_client_execute_with_get_execution_result(
    graphql_server: HTTPServer,
) -> None:
    session = requests.Session()
    transport = PersistentRequestsHTTPTransport(
        session, graphql_server.url_for("/graphql")
    )
    client = Client(transport=transport)
    result: ExecutionResult = client.execute(
        gql(SIMPLE_QUERY), get_execution_result=True
    )
    formatted = result.formatted
    assert formatted["data"] is not None
    assert formatted["data"]["__typename"] == "Query"


def test_client_execute_returns_data_dict(graphql_server: HTTPServer) -> None:
    session = requests.Session()
    transport = PersistentRequestsHTTPTransport(
        session, graphql_server.url_for("/graphql")
    )
    client = Client(transport=transport)
    result = client.execute(gql(SIMPLE_QUERY))
    assert isinstance(result, dict)
    assert result["__typename"] == "Query"


def test_gqlapi_query_full_stack(graphql_server: HTTPServer) -> None:
    gql_api = GqlApi(
        graphql_server.url_for("/graphql"),
        token="Basic test-token",
        validate_schemas=False,
    )
    result = gql_api.query.__wrapped__(gql_api, SIMPLE_QUERY)  # type: ignore[attr-defined]
    assert result["__typename"] == "Query"


def test_gqlapi_query_full_stack_with_variables(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/graphql", method="POST").respond_with_json({
        "data": {"user": {"name": "test-user"}}
    })
    gql_api = GqlApi(
        httpserver.url_for("/graphql"),
        token="Basic test-token",
        validate_schemas=False,
    )
    query = "query User($id: ID!) { user(id: $id) { name } }"
    result = gql_api.query.__wrapped__(gql_api, query, variables={"id": "1"})  # type: ignore[attr-defined]
    assert result["user"]["name"] == "test-user"

    request_body = httpserver.log[0][0].json
    assert "query" in request_body
    assert request_body["variables"] == {"id": "1"}


def test_gqlapi_query_full_stack_transport_error(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/graphql", method="POST").respond_with_json({
        "errors": [{"message": "Something went wrong"}]
    })
    gql_api = GqlApi(
        httpserver.url_for("/graphql"),
        token="Basic test-token",
        validate_schemas=False,
    )
    with pytest.raises(GqlApiError, match="error.*returned with GraphQL response"):
        gql_api.query.__wrapped__(gql_api, SIMPLE_QUERY)  # type: ignore[attr-defined]


def test_gqlapi_pinned_resource_and_template_memoization_and_mutation_isolation(
    mocker: MockerFixture,
) -> None:
    gql_api = GqlApi(
        "http://localhost/graphqlsha/0123456789abcdef",
        validate_schemas=False,
    )
    assert gql_api._is_sha_pinned is True

    query_mock = mocker.patch.object(
        gql_api,
        "query",
        side_effect=[
            {
                "resources": [
                    {
                        "path": "/terraform/resources/s3-private-1.yml",
                        "content": "bucket: private",
                        "sha256sum": "sha-1",
                    }
                ]
            },
            {
                "templates": [
                    {
                        "path": "/templates/role.j2",
                        "template": "kind: Role",
                    }
                ]
            },
        ],
    )

    res1 = gql_api.get_resource("/terraform/resources/s3-private-1.yml")
    res1["content"] = "mutated-by-caller"
    res2 = gql_api.get_resource("/terraform/resources/s3-private-1.yml")

    tpl1 = gql_api.get_template("/templates/role.j2")
    tpl1["template"] = "mutated-template"
    tpl2 = gql_api.get_template("/templates/role.j2")

    assert query_mock.call_count == 2
    assert res2 == {
        "path": "/terraform/resources/s3-private-1.yml",
        "content": "bucket: private",
        "sha256sum": "sha-1",
    }
    assert res2 is not res1
    assert tpl2 == {
        "path": "/templates/role.j2",
        "template": "kind: Role",
    }
    assert tpl2 is not tpl1


def test_gqlapi_separate_clients_for_different_bundle_shas(
    mocker: MockerFixture,
) -> None:
    client_master = GqlApi(
        "http://localhost/graphqlsha/master-sha-111",
        validate_schemas=False,
    )
    client_mr = GqlApi(
        "http://localhost/graphqlsha/mr-sha-222",
        validate_schemas=False,
    )
    mocker.patch.object(
        client_master,
        "query",
        return_value={
            "resources": [{"path": "/res.yml", "content": "v1", "sha256sum": "sha-v1"}]
        },
    )
    mocker.patch.object(
        client_mr,
        "query",
        return_value={
            "resources": [{"path": "/res.yml", "content": "v2", "sha256sum": "sha-v2"}]
        },
    )

    assert client_master.get_resource("/res.yml")["content"] == "v1"
    assert client_mr.get_resource("/res.yml")["content"] == "v2"
    assert client_master.get_resource("/res.yml")["sha256sum"] == "sha-v1"


def test_gqlapi_unpinned_reads_observe_updated_content(
    mocker: MockerFixture,
) -> None:
    gql_api = GqlApi("http://localhost/graphql", validate_schemas=False)
    assert gql_api._is_sha_pinned is False

    query_mock = mocker.patch.object(
        gql_api,
        "query",
        side_effect=[
            {"resources": [{"path": "/res.yml", "content": "old", "sha256sum": "s1"}]},
            {"resources": [{"path": "/res.yml", "content": "new", "sha256sum": "s2"}]},
            {"templates": [{"path": "/tpl.j2", "template": "old-tpl"}]},
            {"templates": [{"path": "/tpl.j2", "template": "new-tpl"}]},
        ],
    )

    assert gql_api.get_resource("/res.yml")["content"] == "old"
    assert gql_api.get_resource("/res.yml")["content"] == "new"
    assert gql_api.get_template("/tpl.j2")["template"] == "old-tpl"
    assert gql_api.get_template("/tpl.j2")["template"] == "new-tpl"
    assert query_mock.call_count == 4


def test_gqlapi_failed_reads_remain_retryable(
    mocker: MockerFixture,
) -> None:
    gql_api = GqlApi(
        "http://localhost/graphqlsha/0123456789abcdef",
        validate_schemas=False,
    )
    query_mock = mocker.patch.object(
        gql_api,
        "query",
        side_effect=[
            GqlApiError("transient failure"),
            {"resources": []},
            {
                "resources": [
                    {"path": "/res.yml", "content": "recovered", "sha256sum": "s1"}
                ]
            },
            GqlApiError("transient template failure"),
            {"templates": [{"path": "/tpl.j2", "template": "recovered-tpl"}]},
        ],
    )

    with pytest.raises(GqlGetResourceError, match="Resource not found"):
        gql_api.get_resource("/res.yml")
    with pytest.raises(
        GqlGetResourceError, match="Expecting one and only one resource"
    ):
        gql_api.get_resource("/res.yml")

    assert gql_api.get_resource("/res.yml")["content"] == "recovered"
    assert gql_api.get_resource("/res.yml")["content"] == "recovered"

    with pytest.raises(GqlGetResourceError, match="Template not found"):
        gql_api.get_template("/tpl.j2")

    assert gql_api.get_template("/tpl.j2")["template"] == "recovered-tpl"
    assert gql_api.get_template("/tpl.j2")["template"] == "recovered-tpl"
    assert query_mock.call_count == 5


def test_gqlapi_cache_cleanup_on_close(
    mocker: MockerFixture,
) -> None:
    gql_api = GqlApi(
        "http://localhost/graphqlsha/0123456789abcdef",
        validate_schemas=False,
    )
    mocker.patch.object(
        gql_api,
        "query",
        side_effect=[
            {"resources": [{"path": "/res.yml", "content": "v1", "sha256sum": "s1"}]},
            {"templates": [{"path": "/tpl.j2", "template": "t1"}]},
        ],
    )

    gql_api.get_resource("/res.yml")
    gql_api.get_template("/tpl.j2")
    assert len(gql_api._resource_cache) == 1
    assert len(gql_api._template_cache) == 1

    gql_api.close()
    assert gql_api._resource_cache == {}
    assert gql_api._template_cache == {}
