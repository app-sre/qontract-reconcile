from __future__ import annotations

from collections.abc import Iterable

from dynatrace import Dynatrace


class DynatraceTokenCreationError(Exception):
    pass


class DynatraceClient:
    def __init__(self, environment_url: str, api: Dynatrace) -> None:
        self._environment_url = environment_url
        self._api = api

    def create_api_token(self, name: str, scopes: Iterable[str]) -> str:
        try:
            token = self._api.tokens.create(name=name, scopes=scopes)
        except Exception as e:
            raise DynatraceTokenCreationError(
                f"{self._environment_url=} Failed to create token for {name=}", e
            ) from e
        return token.token

    @staticmethod
    def create(
        environment_url: str, token: str | None, api: Dynatrace | None
    ) -> DynatraceClient:
        # TODO: test this method
        if not api:
            api = Dynatrace(base_url=environment_url, token=token)
        return DynatraceClient(environment_url=environment_url, api=api)
