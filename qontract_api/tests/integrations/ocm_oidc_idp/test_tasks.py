"""Tests for ocm-oidc-idp tasks."""

from unittest.mock import MagicMock

from qontract_api.integrations.ocm_oidc_idp.tasks import generate_lock_key
from qontract_api.models import Secret


def test_generate_lock_key() -> None:
    vault_target = Secret(
        secret_manager_url="https://vault.example.com", path="rhidp/prod"
    )
    key = generate_lock_key(MagicMock(), "prod", vault_target)
    assert key == "prod:rhidp/prod"
