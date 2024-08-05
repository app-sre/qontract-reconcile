from pytest import raises

from reconcile.test.utils.dynatrace.fixtures import build_dynatrace_api
from reconcile.utils.dynatrace.client import (
    DynatraceAPIToken,
    DynatraceAPITokenCreated,
    DynatraceClient,
    DynatraceTokenCreationError,
    DynatraceTokenRetrievalError,
)


def test_dynatrace_create_token_success() -> None:
    api = build_dynatrace_api(create_token_id="id1", create_token_token="test-token")

    client = DynatraceClient(environment_url="test-env", api=api)
    token = client.create_api_token(name="test-token-name", scopes=["test-scope"])

    assert token == DynatraceAPITokenCreated(token="test-token", id="id1")
    api.tokens.create.assert_called_once_with(
        name="test-token-name", scopes=["test-scope"]
    )


def test_dynatrace_create_token_error() -> None:
    api = build_dynatrace_api(create_error=Exception("test-error"))

    client = DynatraceClient(environment_url="test-env", api=api)

    with raises(DynatraceTokenCreationError):
        client.create_api_token(name="test-token", scopes=["test-scope"])

    api.tokens.create.assert_called_once_with(name="test-token", scopes=["test-scope"])


def test_dynatrace_token_ids_map_for_name_prefix_success() -> None:
    api = build_dynatrace_api(
        list_tokens=[
            ("test-prefix-1", "123"),
            ("test-prefix-2", "456"),
            ("filter-this", "789"),
        ]
    )

    client = DynatraceClient(environment_url="test-env", api=api)
    token_ids = client.get_token_ids_map_for_name_prefix(prefix="test-prefix")

    assert token_ids == {"123": "test-prefix-1", "456": "test-prefix-2"}
    api.tokens.list.assert_called_once_with()


def test_dynatrace_token_ids_map_for_name_empty_prefix_success() -> None:
    api = build_dynatrace_api(
        list_tokens=[
            ("test-prefix-1", "123"),
            ("test-prefix-2", "456"),
            ("other", "789"),
        ]
    )

    client = DynatraceClient(environment_url="test-env", api=api)
    token_ids = client.get_token_ids_map_for_name_prefix(prefix="")

    assert token_ids == {"123": "test-prefix-1", "456": "test-prefix-2", "789": "other"}
    api.tokens.list.assert_called_once_with()


def test_dynatrace_token_ids_map_for_name_prefix_error() -> None:
    api = build_dynatrace_api(list_error=Exception("test-error"))

    client = DynatraceClient(environment_url="test-env", api=api)

    with raises(DynatraceTokenRetrievalError):
        client.get_token_ids_map_for_name_prefix(prefix="test-prefix")

    api.tokens.list.assert_called_once_with()


def test_dynatrace_get_token_success() -> None:
    api = build_dynatrace_api(get_token_id="id1", get_token_scopes=["test-scope"])

    client = DynatraceClient(environment_url="test-env", api=api)
    token = client.get_token_by_id(token_id="id1")

    assert token == DynatraceAPIToken(id="id1", scopes=["test-scope"])
    api.tokens.get.assert_called_once_with(token_id="id1")


def test_dynatrace_get_token_error() -> None:
    api = build_dynatrace_api(get_error=Exception("test-error"))

    client = DynatraceClient(environment_url="test-env", api=api)

    with raises(DynatraceTokenRetrievalError):
        client.get_token_by_id(token_id="id1")

    api.tokens.get.assert_called_once_with(token_id="id1")
