from __future__ import annotations

import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    Self,
)

import requests
from pydantic import BaseModel, ConfigDict

from reconcile.utils.exceptions import AppInterfaceSettingsError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from reconcile.utils.secret_reader import HasSecret


class AcsInstanceAuthProvider(Protocol):
    q_id: str


class AcsInstance(Protocol):
    """Structural subset of the generated `AcsInstanceV1` fragment."""

    name: str
    url: str

    @property
    def credentials(self) -> HasSecret: ...

    @property
    def auth_provider(self) -> AcsInstanceAuthProvider: ...


class AcsBaseApi(BaseModel):
    url: str
    token: str
    timeout: int = 30
    session: requests.Session = requests.Session()

    model_config = ConfigDict(
        validate_by_name=True,
        validate_by_alias=True,
        arbitrary_types_allowed=True,
    )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.session.close()

    @staticmethod
    def filter_acs_instances(
        instances: Sequence[AcsInstance], name: str | None = None
    ) -> list[AcsInstance]:
        if instances:
            filtered = list(instances)
            if name:
                filtered = [i for i in filtered if i.name == name]
                if not filtered:
                    raise AppInterfaceSettingsError(f"ACS instance '{name}' not found")
            return filtered
        raise AppInterfaceSettingsError("No ACS instances found!")

    @staticmethod
    def check_len_attributes(attrs: list[Any], api_data: Any) -> None:
        # generic attribute check function for expected types with valid len()
        for attr in attrs:
            value = api_data.get(attr)
            if value is None or len(value) == 0:
                raise ValueError(
                    f"Attribute '{attr}' must exist and not be empty\n\t{api_data}"
                )

    def generic_request(
        self, path: str, verb: str, json: Any | None = None
    ) -> requests.Response:
        url = f"{self.url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        response = self.session.request(
            verb,
            url,
            headers=headers,
            json=json,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            logging.error(f"{e!s}: {response.text}")
            raise

        return response

    def generic_request_json(
        self, path: str, verb: str, json: Any | None = None
    ) -> Any:
        return self.generic_request(path, verb, json=json).json()
