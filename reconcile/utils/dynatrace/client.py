from __future__ import annotations

from collections.abc import Iterable

from dynatrace import Dynatrace
from dynatrace.environment_v2.tokens_api import ApiTokenUpdate
from pydantic import BaseModel


class DynatraceTokenCreationError(Exception):
    pass


class DynatraceTokenUpdateError(Exception):
    pass


class DynatraceTokenRetrievalError(Exception):
    pass


class DynatraceAPITokenCreated(BaseModel):
    """
    Wrap dynatrace.ApiTokenCreated for decoupling
    """

    token: str
    id: str


class DynatraceAPIToken(BaseModel):
    id: str
    scopes: list[str]


class DynatraceClient:
    def __init__(self, environment_url: str, api: Dynatrace) -> None:
        self._environment_url = environment_url
        self._api = api

    def create_api_token(
        self, name: str, scopes: Iterable[str]
    ) -> DynatraceAPITokenCreated:
        try:
            token = self._api.tokens.create(name=name, scopes=scopes)
        except Exception as e:
            raise DynatraceTokenCreationError(
                f"{self._environment_url=} Failed to create token for {name=}", e
            ) from e
        return DynatraceAPITokenCreated(token=token.token, id=token.id)

    def get_token_ids_map_for_name_prefix(self, prefix: str) -> dict[str, str]:
        try:
            dt_tokens = self._api.tokens.list()
        except Exception as e:
            raise DynatraceTokenRetrievalError(
                f"{self._environment_url=} Failed to retrieve tokens for {prefix=}", e
            ) from e
        return {
            token.id: token.name for token in dt_tokens if token.name.startswith(prefix)
        }

    def get_token_by_id(self, token_id: str) -> DynatraceAPIToken:
        try:
            token = self._api.tokens.get(token_id=token_id)
        except Exception as e:
            raise DynatraceTokenRetrievalError(
                f"{self._environment_url=} Failed to retrieve token for {token_id=}", e
            ) from e
        return DynatraceAPIToken(id=token.id, scopes=token.scopes)

    def update_token(self, token_id: str, name: str, scopes: list[str]) -> None:
        try:
            self._api.tokens.put(
                token_id=token_id,
                api_token=ApiTokenUpdate(
                    name=name,
                    scopes=scopes,
                ),
            )
        except Exception as e:
            raise DynatraceTokenUpdateError(
                f"{self._environment_url=} Failed to update token scopes for {token_id=}",
                e,
            ) from e

    @staticmethod
    def create(
        environment_url: str, token: str | None, api: Dynatrace | None
    ) -> DynatraceClient:
        if not api:
            api = Dynatrace(base_url=environment_url, token=token)
        return DynatraceClient(environment_url=environment_url, api=api)
