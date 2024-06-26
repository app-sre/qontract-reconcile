from __future__ import annotations

from collections.abc import Iterable

from dynatrace import Dynatrace
from pydantic import BaseModel


class DynatraceTokenCreationError(Exception):
    pass


class DynatraceTokenRetrievalError(Exception):
    pass


class DynatraceAPITokenCreated(BaseModel):
    """
    Wrap dynatrace.ApiTokenCreated for decoupling
    """

    token: str
    id: str


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

    def get_token_ids_for_name_prefix(self, prefix: str) -> list[str]:
        try:
            dt_tokens = self._api.tokens.list()
        except Exception as e:
            raise DynatraceTokenRetrievalError(
                f"{self._environment_url=} Failed to retrieve tokens for {prefix=}", e
            ) from e
        return [token.id for token in dt_tokens if token.name.startswith(prefix)]

    @staticmethod
    def create(
        environment_url: str, token: str | None, api: Dynatrace | None
    ) -> DynatraceClient:
        if not api:
            api = Dynatrace(base_url=environment_url, token=token)
        return DynatraceClient(environment_url=environment_url, api=api)
