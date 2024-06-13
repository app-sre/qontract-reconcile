from collections.abc import Callable, Mapping

from dynatrace import Dynatrace
from pytest import raises

from reconcile.utils.dynatrace.client import (
    DynatraceClient,
    DynatraceTokenCreationError,
)


def test_dynatrace_create_token_success(
    dynatrace_api_builder: Callable[[Mapping], Dynatrace],
) -> None:
    api = dynatrace_api_builder({"CREATE_TOKEN_RESULT": "test-token"})

    client = DynatraceClient(environment_url="test-env", api=api)
    token = client.create_api_token(name="test-token-name", scopes=["test-scope"])

    assert token == "test-token"
    api.tokens.create.assert_called_once_with(
        name="test-token-name", scopes=["test-scope"]
    )


def test_dynatrace_create_token_error(
    dynatrace_api_builder: Callable[[Mapping], Dynatrace],
) -> None:
    api = dynatrace_api_builder({"CREATE_TOKEN_RESULT": Exception("test-error")})

    client = DynatraceClient(environment_url="test-env", api=api)

    with raises(DynatraceTokenCreationError):
        client.create_api_token(name="test-token", scopes=["test-scope"])

    api.tokens.create.assert_called_once_with(name="test-token", scopes=["test-scope"])
