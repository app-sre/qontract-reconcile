import logging
from collections.abc import Iterable, Sequence
from typing import Any

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SSOClient(BaseModel):
    client_id: str
    client_name: str
    client_secret: str
    redirect_uris: list[str]
    registration_access_token: str
    registration_client_uri: str
    request_uris: list[str]
    # attribute added by the reconcile code and not part of the SSO client data
    issuer: str
    attributes: dict[str, Any] = {}


class KeycloakInstance(BaseModel):
    url: str
    initial_access_token: str | None = None


class KeycloakAPI:
    def __init__(
        self,
        url: str | None = None,
        initial_access_token: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.url = url
        self.initial_access_token = initial_access_token
        self.timeout = timeout

    def register_client(
        self,
        client_name: str,
        redirect_uris: Sequence[str],
        initiate_login_uri: str,
        request_uris: Sequence[str],
        contacts: Sequence[str],
        group_filter_regex: str | None = None,
    ) -> SSOClient:
        """Create a new SSO client via Keycloak's native registration endpoint."""
        if not self.initial_access_token:
            raise ValueError("initial_access_token is required")
        if not self.url:
            raise ValueError("url is required")

        # /clients-registrations/default accepts Keycloak ClientRepresentation
        # format and supports defaultClientScopes + attributes (needed for
        # regex-filtered-groups). The OIDC endpoint (/openid-connect) does not.
        registration_url = f"{self.url}/clients-registrations/default"

        payload: dict[str, Any] = {
            "clientId": client_name,
            "redirectUris": list(redirect_uris),
            "defaultClientScopes": ["web-origins", "acr", "profile", "roles", "email"],
        }
        if group_filter_regex:
            payload["defaultClientScopes"].append("regex-filtered-groups")
            payload["attributes"] = {"group-filter-regex": group_filter_regex}

        response = requests.post(
            registration_url,
            json=payload,
            headers={"Authorization": f"Bearer {self.initial_access_token}"},
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError:
            logger.error(
                f"Failed to register client with Keycloak at {self.url}: {response.text}"
            )
            raise
        data = response.json()

        return SSOClient(
            client_id=data["clientId"],
            client_name=client_name,
            client_secret=data["secret"],
            redirect_uris=data["redirectUris"],
            registration_access_token=data["registrationAccessToken"],
            registration_client_uri=f"{registration_url}/{data['clientId']}",
            request_uris=data["webOrigins"],
            issuer=self.url,
            attributes=data.get("attributes", {}),
        )

    def delete_client(
        self, registration_client_uri: str, registration_access_token: str
    ) -> None:
        response = requests.delete(
            registration_client_uri,
            headers={"Authorization": f"Bearer {registration_access_token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()


class KeycloakMap:
    def __init__(self, keycloak_instances: Iterable[KeycloakInstance]) -> None:
        self._map = {
            instance.url: KeycloakAPI(
                url=instance.url, initial_access_token=instance.initial_access_token
            )
            for instance in keycloak_instances
        }

    def get(self, keycloak_url: str) -> KeycloakAPI:
        return self._map[keycloak_url]
