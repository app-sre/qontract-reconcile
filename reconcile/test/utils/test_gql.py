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
