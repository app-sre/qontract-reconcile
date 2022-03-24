import requests

from reconcile.utils.gql import (
    GqlApi,
    GqlApiError,
    GqlApiErrorForbiddenSchema,
    GqlApiIntegrationNotFound,
)
from gql import Client  # type: ignore
from gql.transport.exceptions import TransportQueryError  # type: ignore
import pytest

TEST_QUERY = """
{
    integrations: integrations_v1 {
        name
        description
        schemas
    }
}
"""


def test_gqlapi_throws_gqlapierror_exception(mocker):
    mocked_client = mocker.Mock(spec=Client)

    mocked_client.execute.side_effect = Exception("Something went wrong!")
    with pytest.raises(GqlApiError):
        gql_api = GqlApi(mocked_client, validate_schemas=False)
        gql_api.query(TEST_QUERY)

    mocked_client.execute.side_effect = requests.exceptions.ConnectionError(
        "Could not connect with GraphQL API"
    )
    with pytest.raises(GqlApiError):
        gql_api = GqlApi(mocked_client, validate_schemas=False)
        gql_api.query(TEST_QUERY)

    mocked_client.execute.side_effect = TransportQueryError("Error in GraphQL payload")
    with pytest.raises(GqlApiError):
        gql_api = GqlApi(mocked_client, validate_schemas=False)
        gql_api.query(TEST_QUERY)

    mocked_client.execute.side_effect = AssertionError(
        "Transport returned an ExecutionResult without data or errors"
    )
    with pytest.raises(GqlApiError):
        gql_api = GqlApi(mocked_client, validate_schemas=False)
        gql_api.query(TEST_QUERY)


def test_gqlapi_throws_gqlapiintegrationnotfound_exception(mocker):
    mocked_client = mocker.Mock(spec=Client)
    mocked_client.execute.return_value.formatted = {
        "data": {"integrations": [{"name": "INTEGRATION", "schemas": "TEST_SCHEMA"}]}
    }

    with pytest.raises(GqlApiIntegrationNotFound):
        gql_api = GqlApi(mocked_client, "INTEGRATION_NOT_FOUND", validate_schemas=True)
        gql_api.query(TEST_QUERY)


def test_gqlapi_throws_gqlapierrorforbiddenschema_exception(mocker):
    mocked_client = mocker.Mock(spec=Client)
    mocked_client.execute.return_value.formatted = {
        "data": {"integrations": [{"name": "INTEGRATION", "schemas": "TEST_SCHEMA"}]},
        "extensions": {"schemas": ["TEST_SCHEMA", "FORBIDDEN_TEST_SCHEMA"]},
    }

    with pytest.raises(GqlApiErrorForbiddenSchema):
        gql_api = GqlApi(mocked_client, "INTEGRATION", validate_schemas=True)
        gql_api.query(TEST_QUERY)
