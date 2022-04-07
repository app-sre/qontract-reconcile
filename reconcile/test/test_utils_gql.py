import pytest
import requests
from gql.transport.exceptions import TransportQueryError
from reconcile.utils.gql import (
    GqlApi,
    GqlApiError,
    GqlApiErrorForbiddenSchema,
    GqlApiIntegrationNotFound,
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


def test_gqlapi_throws_gqlapierror_when_generic_exception_thrown(mocker):
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = Exception("Something went wrong!")
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)


def test_gqlapi_throws_gqlapierror_when_connectionerror_exception_thrown(mocker):
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = requests.exceptions.ConnectionError(
        "Could not connect with GraphQL API"
    )
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)


def test_gqlapi_throws_gqlapierror_when_transportqueryerror_exception_thrown(mocker):
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = TransportQueryError("Error in GraphQL payload")
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)


def test_gqlapi_throws_gqlapierror_when_assertionerror_exception_thrown(mocker):
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.side_effect = AssertionError(
        "Transport returned an ExecutionResult without data or errors"
    )
    with pytest.raises(GqlApiError):
        gql_api = GqlApi("test_url", "test_token", validate_schemas=False)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)


def test_gqlapi_throws_gqlapiintegrationnotfound_exception(mocker):
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.return_value.formatted = {
        "data": {"integrations": [{"name": "INTEGRATION", "schemas": "TEST_SCHEMA"}]}
    }

    with pytest.raises(GqlApiIntegrationNotFound):
        gql_api = GqlApi(
            "test_url", "test_token", "INTEGRATION_NOT_FOUND", validate_schemas=True
        )
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)


def test_gqlapi_throws_gqlapierrorforbiddenschema_exception(mocker):
    patched_client = mocker.patch("reconcile.utils.gql.Client.execute", autospec=True)
    patched_client.return_value.formatted = {
        "data": {"integrations": [{"name": "INTEGRATION", "schemas": "TEST_SCHEMA"}]},
        "extensions": {"schemas": ["TEST_SCHEMA", "FORBIDDEN_TEST_SCHEMA"]},
    }

    with pytest.raises(GqlApiErrorForbiddenSchema):
        gql_api = GqlApi("test_url", "test_token", "INTEGRATION", validate_schemas=True)
        gql_api.query.__wrapped__(gql_api, TEST_QUERY)
