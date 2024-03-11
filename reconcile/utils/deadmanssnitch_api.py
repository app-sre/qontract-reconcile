import logging
from typing import (
    Optional,
)

import requests
from typing import Any
from pydantic import BaseModel

BASE_URL = "https://api.deadmanssnitch.com/v1/snitches"
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

    def get_cluster_name(self) -> str:
        return self.name.split(".")[1]

    def to_dict(self)-> dict[str,Any]:
        return self.dict(by_alias=True)

class DeadMansSnitchApi:
    def __init__(self, token: str, url: str = BASE_URL) -> None:
        self.token = token
        self.url = url

    def get_snitches(self, tags: list[str]) -> list[Snitch]:
        full_url = f"{self.url}?tags={','.join(tags)}"
        logging.info("Getting snitches for tags:%s", tags)
        response = requests.get(url=full_url, auth=(self.token, ""))
        response.raise_for_status()
        snitches = [Snitch(**item) for item in response.json()]
        return snitches

    def create_snitch(self, payload: dict) -> Optional[Snitch]:
        if payload.get("name") is None or payload.get("interval") is None:
            raise DeadManssnitchException("Invalid payload,name and interval are mandatory")
        headers = {"Content-Type": "application/json"}
        logging.info("Creating new snitch with name:: %s ", payload["name"])
        response = requests.post(url=self.url, json=payload, auth=(self.token, ""), headers=headers)
        response.raise_for_status()
        response_json = response.json()
        return Snitch(**response_json)

    def delete_snitch(self, token: str) -> None:
        delete_api_url = f"{self.url}/{token}"
        response = requests.delete(url=delete_api_url, auth=(self.token, ""))
        response.raise_for_status()
        logging.info("Successfully deleted snich: %s", token)
