from collections.abc import Iterable
from unittest.mock import create_autospec

from dynatrace import Dynatrace
from dynatrace.environment_v2.tokens_api import ApiToken, ApiTokenCreated, TokenService


def build_dynatrace_api(
    create_token_id: str | None = None,
    create_token_token: str | None = None,
    create_error: Exception | None = None,
    list_tokens: Iterable[tuple[str, str]] | None = None,
    list_error: Exception | None = None,
    get_token_id: str | None = None,
    get_token_scopes: Iterable[str] | None = None,
    get_error: Exception | None = None,
) -> Dynatrace:
    dynatrace_mock = create_autospec(spec=Dynatrace)
    token_service = create_autospec(spec=TokenService)
    dynatrace_mock.tokens = token_service

    if create_token_token and create_token_id:
        token = create_autospec(spec=ApiTokenCreated)
        token.id = create_token_id
        token.token = create_token_token
        token_service.create.return_value = token
    elif create_error:
        # For raising exceptions
        token_service.create.side_effect = create_error

    if list_tokens:
        listed_tokens = []
        for token_tup in list_tokens:
            token = create_autospec(spec=ApiToken)
            token.id = token_tup[1]
            token.name = token_tup[0]
            listed_tokens.append(token)
        token_service.list.return_value = listed_tokens
    elif list_error:
        # For raising exceptions
        token_service.list.side_effect = list_error

    if get_token_id and get_token_scopes:
        token = create_autospec(spec=ApiToken)
        token.id = get_token_id
        token.scopes = list(get_token_scopes)
        token_service.get.return_value = token
    elif get_error:
        # For raising exceptions
        token_service.get.side_effect = get_error
    return dynatrace_mock
