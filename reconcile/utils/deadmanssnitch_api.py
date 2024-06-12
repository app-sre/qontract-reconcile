import logging
from typing import (
    Any,
    Self,
)

import requests
from pydantic import BaseModel

BASE_URL = "https://api.deadmanssnitch.com/v1/snitches"
REQUEST_TIMEOUT = 60


class DeadManssnitchException(Exception):
    pass


class Snitch(BaseModel):
    token: str
    href: str
    name: str
    tags: list[str]
    notes: str
    status: str
    check_in_url: str
    interval: str
    alert_type: str
    alert_email: list[str]
    vault_data: str | None

    def needs_vault_update(self) -> bool:
        return self.vault_data is not None and self.check_in_url != self.vault_data


class DeadMansSnitchApi:
    def __init__(
        self, token: str, url: str = BASE_URL, timeout: int = REQUEST_TIMEOUT
    ) -> None:
        self.token = token
        self.url = url
        self.timeout = timeout
        self.session = requests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.session.close()

    def get_snitches(self, tags: list[str]) -> list[Snitch]:
        logging.debug("Getting snitches for tags:%s", tags)
        response = self.session.get(
            url=self.url,
            params={"tags": ",".join(tags)},
            auth=(self.token, ""),
            timeout=self.timeout,
        )
        response.raise_for_status()
        snitches = [Snitch(**item) for item in response.json()]
        return snitches

    def create_snitch(self, payload: dict) -> Snitch:
        if payload.get("name") is None or payload.get("interval") is None:
            raise DeadManssnitchException(
                "Invalid payload,name and interval are mandatory"
            )
        headers = {"Content-Type": "application/json"}
        logging.debug("Creating new snitch with name:: %s ", payload["name"])
        response = self.session.post(
            url=self.url,
            json=payload,
            auth=(self.token, ""),
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        response_json = response.json()
        return Snitch(**response_json)

    def delete_snitch(self, token: str) -> None:
        delete_api_url = f"{self.url}/{token}"
        response = self.session.delete(
            url=delete_api_url, auth=(self.token, ""), timeout=self.timeout
        )
        response.raise_for_status()
        logging.debug("Successfully deleted snich: %s", token)
