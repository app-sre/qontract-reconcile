import logging
import os
from base64 import b64encode
from collections.abc import Mapping
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
)
from urllib.parse import urljoin

import requests

from reconcile.utils.secret_reader import (
    HasSecret,
    SecretReaderBase,
)

LOG = logging.getLogger(__name__)


@dataclass
class DashdotDBSecret:
    path: str
    field: str
    q_format: Optional[str]
    version: Optional[int]


DASHDOTDB_SECRET = DashdotDBSecret(
    field="",
    path=os.environ.get("DASHDOTDB_SECRET", "app-sre/dashdot/auth-proxy-production"),
    q_format=None,
    version=None,
)


class DashdotdbBase:
    def __init__(
        self,
        dry_run: bool,
        thread_pool_size: int,
        marker: str,
        scope: str,
        secret_reader: SecretReaderBase,
    ) -> None:
        self.dry_run = dry_run
        self.thread_pool_size = thread_pool_size
        self.secret_reader = secret_reader
        self.secret_content = self.secret_reader.read_all_secret(DASHDOTDB_SECRET)
        self.dashdotdb_url = self.secret_content["url"]
        self.dashdotdb_user = self.secret_content["username"]
        self.dashdotdb_pass = self.secret_content["password"]
        self.logmarker = marker
        self.scope = scope
        self.dashdotdb_token = Optional[str]

    def _get_token(self) -> None:
        if self.dry_run:
            return None

        params = {"scope": self.scope}
        endpoint = f"{self.dashdotdb_url}/api/v1/" f"token"
        response = requests.get(
            url=endpoint,
            params=params,
            auth=(self.dashdotdb_user, self.dashdotdb_pass),
            timeout=(5, 120),
        )
        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as details:
            LOG.error(
                "%s error retrieving token for %s data: %s",
                self.logmarker,
                self.scope,
                details,
            )
            return None
        self.dashdotdb_token = response.text.replace('"', "").strip()

    def _close_token(self) -> None:
        if self.dry_run:
            return None

        params = {"scope": self.scope}
        endpoint = f"{self.dashdotdb_url}/api/v1/" f"token/{self.dashdotdb_token}"
        response = requests.delete(
            url=endpoint,
            params=params,
            auth=(self.dashdotdb_user, self.dashdotdb_pass),
            timeout=(5, 120),
        )
        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as details:
            LOG.error(
                "%s error closing token for %s data: %s",
                self.logmarker,
                self.scope,
                details,
            )

    def _do_post(
        self,
        endpoint: str,
        data: Mapping[Any, Any],
        timeout: tuple[int, int] = (5, 120),
    ) -> requests.Response:
        headers: dict[str, str] = {}
        if self.dashdotdb_token:
            headers["X-Auth"] = str(self.dashdotdb_token)
        return requests.post(
            url=endpoint,
            json=data,
            headers=headers,
            auth=(self.dashdotdb_user, self.dashdotdb_pass),
            timeout=timeout,
        )

    def _do_get(
        self,
        endpoint: str,
        params: Mapping[Any, Any],
        timeout: tuple[int, int] = (5, 120),
    ) -> requests.Response:
        return requests.get(
            url=endpoint,
            params=params,
            auth=(self.dashdotdb_user, self.dashdotdb_pass),
            timeout=timeout,
        )

    def _promget(
        self,
        url: str,
        params: Optional[Mapping[Any, Any]],
        token: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        ssl_verify: bool = True,
        uri: str = "api/v1/query",
    ) -> dict[Any, Any]:
        url = urljoin((f"{url}"), uri)
        LOG.debug("%s Fetching prom payload from %s?%s", self.logmarker, url, params)
        headers = {
            "accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            headers[
                "Authorization"
            ] = f"Basic {b64encode(f'{username}:{password}'.encode()).decode('utf-8')}"
        response = requests.get(
            url, params=params, headers=headers, verify=ssl_verify, timeout=(5, 120)
        )
        response.raise_for_status()

        data = response.json()
        # TODO ensure len response == 1
        # return ans['data']['result']
        return data

    def _get_automation_token(self, secret: HasSecret) -> str:
        return self.secret_reader.read_secret(secret=secret)
