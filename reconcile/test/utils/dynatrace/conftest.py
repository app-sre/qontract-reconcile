from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import create_autospec

import pytest
from dynatrace import Dynatrace
from dynatrace.environment_v2.tokens_api import ApiTokenCreated, TokenService


@pytest.fixture
def dynatrace_api_builder() -> Callable[[Mapping], Dynatrace]:
    def builder(data: Mapping[str, Any]) -> Dynatrace:
        dynatrace_mock = create_autospec(spec=Dynatrace)
        token_service = create_autospec(spec=TokenService)
        dynatrace_mock.tokens = token_service

        token_created_result = data.get("CREATE_TOKEN_RESULT")
        if isinstance(token_created_result, str):
            token = create_autospec(spec=ApiTokenCreated)
            token.token = token_created_result
            token_service.create.return_value = token
        else:
            token_service.create.side_effect = token_created_result
        return dynatrace_mock

    return builder
