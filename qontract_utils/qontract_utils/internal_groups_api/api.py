"""Internal Groups API client with OAuth2 client-credentials token management."""

import time

import requests
import structlog

from qontract_utils.internal_groups_api.models import Group, GroupMember

logger = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT = 30
_TOKEN_BUFFER_SECONDS = 30  # Refresh token this many seconds before expiry
_HTTP_UNAUTHORIZED = 401


class InternalGroupsApi:
    """Stateless HTTP client for the internal groups proxy API.

    Handles OAuth2 client-credentials token acquisition and renewal.
    Tokens are cached in-memory (per instance) and refreshed before expiry.

    This is Layer 1 (Pure Communication) following ADR-014.

    Args:
        base_url: Base URL of the internal groups API (e.g., "https://groups.example.com")
        token_url: OAuth2 token endpoint URL
        client_id: OAuth2 client ID
        client_secret: OAuth2 client secret (resolved value)
        timeout: HTTP request timeout in seconds
    """

    def __init__(
        self,
        base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def _acquire_token(self) -> str:
        """Acquire a new OAuth2 access token using client-credentials flow."""
        logger.debug("Acquiring OAuth2 token", token_url=self.token_url)
        response = requests.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 300)
        self._token_expires_at = time.monotonic() + expires_in - _TOKEN_BUFFER_SECONDS
        return self._token

    def _get_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        return self._acquire_token()

    def _get(self, path: str) -> dict:
        """Execute an authenticated GET request, retrying once on 401."""
        token = self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        url = f"{self.base_url}{path}"

        response = requests.get(url, headers=headers, timeout=self.timeout)

        if response.status_code == _HTTP_UNAUTHORIZED:
            # Token may have been invalidated — force refresh and retry once
            logger.debug("Received 401, refreshing token and retrying")
            self._token = None
            self._token_expires_at = 0.0
            token = self._acquire_token()
            headers = {"Authorization": f"Bearer {token}"}
            response = requests.get(url, headers=headers, timeout=self.timeout)

        response.raise_for_status()
        return response.json()

    def get_group_members(self, group_name: str) -> Group:
        """Fetch members of an LDAP group.

        Args:
            group_name: LDAP group name

        Returns:
            Group with its members

        Raises:
            requests.HTTPError: If the API returns a non-2xx status
        """
        data = self._get(f"/groups/{group_name}/members")
        members = [GroupMember(id=m["id"]) for m in data.get("members", [])]
        return Group(name=group_name, members=members)
