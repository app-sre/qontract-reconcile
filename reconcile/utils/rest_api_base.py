import threading
from typing import Any
from urllib.parse import urljoin

import requests


def get_next_url(links: dict[str, dict[str, str]]) -> str | None:
    """Parse response header 'Link' attribute and return the next page url if exists.

    See
    * https://gitlab.com/glitchtip/glitchtip-backend/-/blob/master/glitchtip/pagination.py#L34
    * https://requests.readthedocs.io/en/latest/api/?highlight=links#requests.Response.links
    """
    if links.get("next", {}).get("results", "false") == "true":
        return links["next"]["url"]
    return None


class ApiBase:
    """This class provides a common standard for REST API clients."""

    def __init__(
        self,
        host: str,
        token: str,
        max_retries: int | None = None,
        read_timeout: float | None = None,
    ) -> None:
        self.host = host
        self.token = token
        self.max_retries = max_retries if max_retries is not None else 3
        self.read_timeout = read_timeout if read_timeout is not None else 30
        self._thread_local = threading.local()

    @property
    def _session(self) -> requests.Session:
        try:
            return self._thread_local.session
        except AttributeError:
            # todo timeout
            self._thread_local.session = requests.Session()
            self._thread_local.session.mount(
                "https://", requests.adapters.HTTPAdapter(max_retries=self.max_retries)
            )
            self._thread_local.session.mount(
                "http://", requests.adapters.HTTPAdapter(max_retries=self.max_retries)
            )
            self._thread_local.session.headers.update({
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            })
            return self._thread_local.session

    def _get(self, url: str) -> dict[str, Any]:
        response = self._session.get(urljoin(self.host, url), timeout=self.read_timeout)
        return response.json()

    def _list(self, url: str, limit: int = 100) -> list[dict[str, Any]]:
        response = self._session.get(
            urljoin(self.host, url), params={"limit": limit}, timeout=self.read_timeout
        )
        response.raise_for_status()
        results = response.json()
        if response.links:
            # handle pagination
            while next_url := get_next_url(response.links):
                response = self._session.get(next_url)
                results += response.json()
        return results

    def _post(self, url: str, data: dict | None = None) -> dict[str, Any]:
        response = self._session.post(
            urljoin(self.host, url), json=data, timeout=self.read_timeout
        )
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json()

    def _put(self, url: str, data: dict | None = None) -> dict[str, Any]:
        response = self._session.put(
            urljoin(self.host, url), json=data, timeout=self.read_timeout
        )
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json()

    def _delete(self, url: str) -> None:
        response = self._session.delete(urljoin(self.host, url), timeout=None)
        response.raise_for_status()
