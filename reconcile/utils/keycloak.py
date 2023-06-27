from typing import (
    Iterable,
    Optional,
    Sequence,
)

import requests
from pydantic import BaseModel


class SSOClient(BaseModel):
    # these attributes come from the Keycloak API
    client_id: str
    client_id_issued_at: int
    client_name: str
    client_secret: str
    client_secret_expires_at: int
    grant_types: list[str]
    redirect_uris: list[str]
    registration_access_token: str
    registration_client_uri: str
    request_uris: list[str]
    response_types: list[str]
    subject_type: str
    tls_client_certificate_bound_access_tokens: bool
    token_endpoint_auth_method: str
    # these attributes are added by the reconcile code
    issuer: str


class KeycloakInstance(BaseModel):
    url: str
    initial_access_token: Optional[str] = None


class KeycloakAPI:
    def __init__(
        self, url: str, initial_access_token: Optional[str] = None, timeout: int = 30
    ) -> None:
        self.url = url
        self.initial_access_token = initial_access_token
        self.timeout = timeout
        self._init_openid_configuration()

    def _init_openid_configuration(self) -> None:
        self._openid_configuration = requests.get(
            f"{self.url}/.well-known/openid-configuration",
            timeout=self.timeout,
        ).json()

    def register_client(
        self,
        client_name: str,
        redirect_uris: Sequence[str],
        initiate_login_uri: str,
        request_uris: Sequence[str],
        contacts: Sequence[str],
    ) -> SSOClient:
        """Create a new SSO client."""
        if not self.initial_access_token:
            raise ValueError("initial_access_token is required")

        response = requests.post(
            self._openid_configuration["registration_endpoint"],
            json={
                "client_name": client_name,
                "redirect_uris": redirect_uris,
                "response_types": ["code"],
                "grant_types": ["authorization_code"],
                "application_type": "web",
                "contacts": contacts,
                "initiate_login_uri": initiate_login_uri,
                "request_uris": request_uris,
            },
            headers={"Authorization": f"Bearer {self.initial_access_token}"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return SSOClient(**response.json(), issuer=self.url)

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
