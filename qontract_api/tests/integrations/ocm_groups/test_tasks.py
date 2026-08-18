"""Tests for ocm-groups tasks."""

from unittest.mock import MagicMock

from qontract_api.integrations.ocm_groups.tasks import generate_lock_key
from qontract_api.ocm.domain import OcmConnectionParams


def test_generate_lock_key() -> None:
    ocm_connection = OcmConnectionParams(
        secret_manager_url="https://vault.example.com",
        path="ocm/prod",
        ocm_url="https://api.openshift.com",
        access_token_url="https://sso.redhat.com/token",
        access_token_client_id="client-id",
    )
    key = generate_lock_key(MagicMock(), "prod", ocm_connection)
    assert key == "ocm-groups:prod:https://api.openshift.com"
