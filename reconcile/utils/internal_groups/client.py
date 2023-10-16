from typing import (
    Any,
    Optional,
    Self,
)

import requests
from oauthlib.oauth2 import (
    BackendApplicationClient,
    TokenExpiredError,
)
from requests import Response
from requests_oauthlib import OAuth2Session
from sretoolbox.utils import retry

from reconcile.utils.internal_groups.models import Group


class NotFound(Exception):
    """Not found exception."""


class InternalGroupsApi:
    """Internal groups API client."""

    def __init__(
        self, api_url: str, issuer_url: str, client_id: str, client_secret: str
    ):
        self.api_url = api_url
        self.issuer_url = issuer_url
        self.client_id = client_id
        self.client_secret = client_secret
        client = BackendApplicationClient(client_id=self.client_id)
        self._client = OAuth2Session(self.client_id, client=client)

    def _fetch_token(self) -> dict:
        self._client.token = {}
        return self._client.fetch_token(
            token_url=f"{self.issuer_url}/protocol/openid-connect/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

    def _check_response(self, resp: requests.Response) -> None:
        """Check response."""
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise NotFound
            raise

    def __enter__(self) -> Self:
        """Fetch token."""
        if not self._client.token:
            self._client.token = self._fetch_token()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        pass

    @retry(exceptions=(TokenExpiredError,), max_attempts=2)
    def _request(
        self, method: str, url: str, json: Optional[dict[Any, Any]] = None
    ) -> Response:
        try:
            return self._client.request(
                method=method,
                url=url,
                json=json,
                # Content-Type is required for GET too :(
                headers={"Content-Type": "application/json"},
            )
        except TokenExpiredError:
            self._client.token = self._fetch_token()
            raise

    def close(self) -> None:
        """Close client session."""
        self._client.close()

    def group(self, name: str) -> dict:
        """Get a group by name."""
        resp = self._request("GET", f"{self.api_url}/v1/groups/{name}")
        self._check_response(resp)
        return resp.json()

    def delete_group(self, name: str) -> None:
        """Delete a group by name."""
        resp = self._request("DELETE", f"{self.api_url}/v1/groups/{name}")
        self._check_response(resp)

    def create_group(self, data: dict) -> dict:
        """Create a group."""
        resp = self._request("POST", f"{self.api_url}/v1/groups/", json=data)
        self._check_response(resp)
        return resp.json()

    def update_group(self, name: str, data: dict) -> dict:
        """Update a group."""
        resp = self._request(
            "PATCH",
            f"{self.api_url}/v1/groups/{name}",
            json=data,
        )
        self._check_response(resp)
        return resp.json()


class InternalGroupsClient:
    """High level Internal groups client."""

    def __init__(
        self,
        api_url: str,
        issuer_url: str,
        client_id: str,
        client_secret: str,
        api_class: type[InternalGroupsApi] = InternalGroupsApi,
    ):
        self._api = api_class(api_url, issuer_url, client_id, client_secret)

    def close(self) -> None:
        """Close client session."""
        self._api.close()

    def group(self, name: str) -> Group:
        """Get group by name."""
        with self._api as api:
            return Group(**api.group(name))

    def create_group(self, group: Group) -> Group:
        """Create group."""
        with self._api as api:
            return Group(
                **api.create_group(
                    data=group.dict(by_alias=True),
                )
            )

    def delete_group(self, name: str) -> None:
        """Delete group."""
        with self._api as api:
            api.delete_group(name)

    def update_group(self, group: Group) -> Group:
        """Update group."""
        with self._api as api:
            return Group(
                **api.update_group(
                    name=group.name,
                    data=group.dict(by_alias=True),
                )
            )
