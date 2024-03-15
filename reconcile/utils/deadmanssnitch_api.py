import logging
from typing import (
    Any,
    Optional,
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
    vault_data: Optional[str]

    def get_cluster_name(self) -> str:
        return self.name.split(".")[1]


class DeadMansSnitchApi:
    def __init__(self, token: str, url: str = BASE_URL) -> None:
        self.token = token
        self.url = url
        self.session = requests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.session.close()

    def get_snitches(self, tags: list[str]) -> list[Snitch]:
        full_url = f"{self.url}?tags={','.join(tags)}"
        logging.debug("Getting snitches for tags:%s", tags)
        response = self.session.get(
            url=full_url, auth=(self.token, ""), timeout=REQUEST_TIMEOUT
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
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        response_json = response.json()
        return Snitch(**response_json)

    def delete_snitch(self, token: str) -> None:
        delete_api_url = f"{self.url}/{token}"
        response = self.session.delete(
            url=delete_api_url, auth=(self.token, ""), timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        logging.debug("Successfully deleted snich: %s", token)
