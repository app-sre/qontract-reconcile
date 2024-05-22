import logging
from typing import Any, Self
from urllib.parse import urljoin

import requests
from urllib3 import Retry

from reconcile.utils.oauth2_backend_application_session import (
    OAuth2BackendApplicationSession,
)


def get_next_url(links: dict[str, dict[str, str]]) -> str | None:
    """Parse response header 'Link' attribute and return the next page url if exists.

    See
    * https://gitlab.com/glitchtip/glitchtip-backend/-/blob/master/glitchtip/pagination.py#L34
    * https://requests.readthedocs.io/en/latest/api/?highlight=links#requests.Response.links
    """
    if links.get("next", {}).get("results", "false") == "true":
        return links["next"]["url"]
    return None


class BearerTokenAuth(requests.auth.AuthBase):
    """Use this class to add a Bearer token to the request headers."""

    def __init__(self, token: str):
        self.token = token

    def __eq__(self, other: Any) -> bool:
        return self.token == getattr(other, "token", None)

    def __ne__(self, other: Any) -> bool:
        return not self == other

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


class ApiBase:
    """This class provides a common standard for REST API clients."""

    def __init__(
        self,
        host: str,
        auth: requests.auth.AuthBase | None = None,
        max_retries: int | Retry | None = None,
        read_timeout: float | None = None,
        session: requests.Session | OAuth2BackendApplicationSession | None = None,
    ) -> None:
        self.host = host
        self.max_retries = max_retries if max_retries is not None else 3
        self.read_timeout = read_timeout if read_timeout is not None else 30
        self.session = session or requests.Session()
        if auth:
            self.session.auth = auth
        for prefix in ["http://", "https://"]:
            self.session.mount(
                prefix,
                requests.adapters.HTTPAdapter(max_retries=self.max_retries),
            )
        self.session.headers.update({
            "Content-Type": "application/json",
        })

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        self.session.close()

    def _get(self, url: str) -> dict[str, Any]:
        response = self.session.get(urljoin(self.host, url), timeout=self.read_timeout)
        response.raise_for_status()
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            logging.error(
                f"Failed to decode JSON response from {url}"
                f"Response: {response.text}"
            )
            raise

    def _list(
        self, url: str, params: dict | None = None, attribute: str | None = None
    ) -> list[dict[str, Any]]:
        response = self.session.get(
            urljoin(self.host, url), params=params, timeout=self.read_timeout
        )
        response.raise_for_status()
        results = response.json()
        if response.links:
            # handle pagination
            while next_url := get_next_url(response.links):
                response = self.session.get(next_url)
                results += response.json()
        if attribute:
            return results[attribute]
        return results

    def _post(self, url: str, data: dict | None = None) -> dict[str, Any]:
        response = self.session.post(
            urljoin(self.host, url), json=data, timeout=self.read_timeout
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.text:
            return {}
        return response.json()

    def _put(self, url: str, data: dict | None = None) -> dict[str, Any]:
        response = self.session.put(
            urljoin(self.host, url), json=data, timeout=self.read_timeout
        )
        response.raise_for_status()
        if response.status_code == 204 or not response.text:
            return {}
        return response.json()

    def _delete(self, url: str) -> None:
        response = self.session.delete(urljoin(self.host, url), timeout=None)
        response.raise_for_status()
