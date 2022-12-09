import logging
import os
from urllib.parse import urljoin

import requests

from reconcile import queries
from reconcile.utils.secret_reader import (
    HasSecret,
    SecretReader,
)

LOG = logging.getLogger(__name__)

DASHDOTDB_SECRET = os.environ.get(
    "DASHDOTDB_SECRET", "app-sre/dashdot/auth-proxy-production"
)


class DashdotdbBase:
    def __init__(self, dry_run, thread_pool_size, marker, scope):
        self.dry_run = dry_run
        self.thread_pool_size = thread_pool_size
        self.settings = queries.get_app_interface_settings()
        self.secret_reader = SecretReader(settings=self.settings)
        self.secret_content = self.secret_reader.read_all({"path": DASHDOTDB_SECRET})
        self.dashdotdb_url = self.secret_content["url"]
        self.dashdotdb_user = self.secret_content["username"]
        self.dashdotdb_pass = self.secret_content["password"]
        self.logmarker = marker
        self.scope = scope

    def _get_token(self):
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

    def _close_token(self):
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

    def _do_post(self, endpoint, data, timeout=(5, 120)):
        return requests.post(
            url=endpoint,
            json=data,
            headers={"X-Auth": self.dashdotdb_token},
            auth=(self.dashdotdb_user, self.dashdotdb_pass),
            timeout=timeout,
        )

    def _promget(self, url, params, token=None, ssl_verify=True, uri="api/v1/query"):
        url = urljoin((f"{url}"), uri)
        LOG.debug("%s Fetching prom payload from %s?%s", self.logmarker, url, params)
        headers = {
            "accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = requests.get(
            url, params=params, headers=headers, verify=ssl_verify, timeout=(5, 120)
        )
        response.raise_for_status()

        response = response.json()
        # TODO ensure len response == 1
        # return response['data']['result']
        return response

    def _get_automationtoken(self, tokenpath):
        autotoken_reader = SecretReader(settings=self.settings)
        token = autotoken_reader.read(tokenpath)
        return token

    def _get_automation_token(self, secret: HasSecret) -> str:
        secret_reader = SecretReader(settings=self.settings)

        # This will change later when SecretReader fully supports 'HasSecret'
        return secret_reader.read(
            {
                "path": secret.path,
                "field": secret.field,
                "format": secret.q_format,
                "version": secret.version,
            }
        )
