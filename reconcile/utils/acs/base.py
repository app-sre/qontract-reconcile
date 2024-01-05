from typing import (
    Any,
    Optional,
    Self,
)

import requests

class AcsBaseApi:
    def __init__(
        self,
        instance: Any,
        timeout: int = 30,
    ) -> None:
        self.base_url = instance["url"]
        self.token = instance["token"]
        self.timeout = timeout
        self.session = requests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.session.close()

    def generic_request(
        self, path: str, verb: str, json: Optional[Any] = None
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        response = self.session.request(
            verb,
            url,
            headers=headers,
            json=json,
            timeout=self.timeout,
        )

        response.raise_for_status()
        return response
