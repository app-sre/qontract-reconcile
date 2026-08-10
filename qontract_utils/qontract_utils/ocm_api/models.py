"""OCM domain models.

Frozen Pydantic models scoped to only the fields actually consumed by the first
qontract-api client of this module (reconcile/rhidp/sso_client). They are
deliberately decoupled from the raw wire-format schemas in _raw_client.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OcmSubscriptionLabel(BaseModel, frozen=True):
    key: str
    value: str
    subscription_id: str


class OcmOrganizationLabel(BaseModel, frozen=True):
    key: str
    value: str
    organization_id: str


class OcmSubscription(BaseModel, frozen=True):
    id: str
    organization_id: str
    status: str
    managed: bool


class OcmCluster(BaseModel, frozen=True):
    id: str
    name: str
    subscription_id: str
    console_url: str | None
    external_auth_enabled: bool


class OcmIdentityProvider(BaseModel, frozen=True):
    """A foreign/unmanaged identity provider this client does not create or update.

    Covers e.g. GithubIdentityProvider or any other OCM-supported type. Used to
    classify existing identity providers on a cluster and, where appropriate, delete
    them.
    """

    type: str
    name: str
    id: str | None = None


class OcmIdentityProviderOidcOpenIdClaims(BaseModel, frozen=True):
    email: list[str] = ["email"]
    name: list[str] = ["name"]
    preferred_username: list[str] = ["preferred_username"]
    groups: list[str] = []


class OcmIdentityProviderOidcOpenId(BaseModel, frozen=True):
    client_id: str
    # OCM never returns the client secret on read - excluded from equality so that a
    # freshly-read "current" instance (secret=None) can still compare equal to a
    # "desired" instance built with the real secret.
    client_secret: str | None = None
    issuer: str
    claims: OcmIdentityProviderOidcOpenIdClaims = OcmIdentityProviderOidcOpenIdClaims()

    # Custom __eq__ ignores client_secret, so instances are intentionally unhashable.
    # mypy has no clean way to type this pattern outside of @dataclass.
    __hash__ = None  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OcmIdentityProviderOidcOpenId):
            return NotImplemented
        return (
            self.client_id == other.client_id
            and self.issuer == other.issuer
            and self.claims == other.claims
        )


class OcmIdentityProviderOidc(BaseModel, frozen=True):
    type: Literal["OpenIDIdentityProvider"] = "OpenIDIdentityProvider"
    name: str
    id: str | None = None
    mapping_method: str = "add"
    open_id: OcmIdentityProviderOidcOpenId

    # Custom __eq__ ignores id (OCM-assigned, unknown for desired-state instances), so
    # instances are intentionally unhashable. mypy has no clean way to type this
    # pattern outside of @dataclass.
    __hash__ = None  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OcmIdentityProviderOidc):
            return NotImplemented
        return self.name == other.name and self.open_id == other.open_id
