"""OCM domain models.

Frozen Pydantic models scoped to only the fields actually consumed by the first
qontract-api client of this module (reconcile/rhidp/sso_client). They are
deliberately decoupled from the raw wire-format schemas in _raw_client.py.
"""

from __future__ import annotations

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
