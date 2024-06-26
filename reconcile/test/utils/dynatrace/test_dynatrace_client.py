from collections.abc import Callable, Mapping

from dynatrace import Dynatrace
from pytest import raises

from reconcile.utils.dynatrace.client import (
    DynatraceAPITokenCreated,
    DynatraceClient,
    DynatraceTokenCreationError,
    DynatraceTokenRetrievalError,
)


def test_dynatrace_create_token_success(
    dynatrace_api_builder: Callable[[Mapping], Dynatrace],
) -> None:
    api = dynatrace_api_builder({"CREATE_TOKEN_RESULT": ("id1", "test-token")})

    client = DynatraceClient.create(environment_url="test-env", token=None, api=api)
    token = client.create_api_token(name="test-token-name", scopes=["test-scope"])

    assert token == DynatraceAPITokenCreated(token="test-token", id="id1")
    api.tokens.create.assert_called_once_with(
        name="test-token-name", scopes=["test-scope"]
    )


def test_dynatrace_create_token_error(
    dynatrace_api_builder: Callable[[Mapping], Dynatrace],
) -> None:
    api = dynatrace_api_builder({"CREATE_TOKEN_RESULT": Exception("test-error")})

    client = DynatraceClient.create(environment_url="test-env", token=None, api=api)

    with raises(DynatraceTokenCreationError):
        client.create_api_token(name="test-token", scopes=["test-scope"])

    api.tokens.create.assert_called_once_with(name="test-token", scopes=["test-scope"])


def test_dynatrace_token_ids_for_name_prefix_success(
    dynatrace_api_builder: Callable[[Mapping], Dynatrace],
) -> None:
    api = dynatrace_api_builder({
        "LIST_TOKEN_RESULT": [
            ("test-prefix-1", "123"),
            ("test-prefix-2", "456"),
            ("filter-this", "789"),
        ]
    })

    client = DynatraceClient.create(environment_url="test-env", token=None, api=api)
    token_ids = client.get_token_ids_for_name_prefix(prefix="test-prefix")

    assert token_ids == ["123", "456"]
    api.tokens.list.assert_called_once_with()


def test_dynatrace_token_ids_for_name_empty_prefix_success(
    dynatrace_api_builder: Callable[[Mapping], Dynatrace],
) -> None:
    api = dynatrace_api_builder({
        "LIST_TOKEN_RESULT": [
            ("test-prefix-1", "123"),
            ("test-prefix-2", "456"),
            ("filter-this", "789"),
        ]
    })

    client = DynatraceClient.create(environment_url="test-env", token=None, api=api)
    token_ids = client.get_token_ids_for_name_prefix(prefix="")

    assert token_ids == ["123", "456", "789"]
    api.tokens.list.assert_called_once_with()


def test_dynatrace_token_ids_for_name_prefix_error(
    dynatrace_api_builder: Callable[[Mapping], Dynatrace],
) -> None:
    api = dynatrace_api_builder({"LIST_TOKEN_RESULT": Exception("test-error")})

    client = DynatraceClient.create(environment_url="test-env", token=None, api=api)

    with raises(DynatraceTokenRetrievalError):
        client.get_token_ids_for_name_prefix(prefix="test-prefix")

    api.tokens.list.assert_called_once_with()
