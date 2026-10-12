"""Tests for the managed-sso-client shared utilities."""

from __future__ import annotations

from qontract_utils.managed_sso_client import derive_managed_sso_client_id


def test_derive_managed_sso_client_id_joins_and_lowercases() -> None:
    assert derive_managed_sso_client_id("My-App", "CI-Bot") == "my-app-ci-bot"
