from __future__ import annotations

import pytest

from reconcile.gql_definitions.acs.acs_instances import (
    AcsInstanceAuthProviderV1,
    AcsInstanceV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.acs.base import AcsBaseApi
from reconcile.utils.exceptions import AppInterfaceSettingsError


def _make_instance(name: str) -> AcsInstanceV1:
    return AcsInstanceV1(
        name=name,
        url=f"https://{name}.example.com",
        credentials=VaultSecret(
            path="secret/path", field="token", version=None, format=None, url=None
        ),
        authProvider=AcsInstanceAuthProviderV1(name="sso", id="auth-id"),
    )


def test_filter_acs_instances_returns_all() -> None:
    instances = [_make_instance("acs-a"), _make_instance("acs-b")]

    result = AcsBaseApi.filter_acs_instances(instances)

    assert len(result) == 2
    assert {i.name for i in result} == {"acs-a", "acs-b"}


def test_filter_acs_instances_filters_by_name() -> None:
    instances = [_make_instance("acs-a"), _make_instance("acs-b")]

    result = AcsBaseApi.filter_acs_instances(instances, name="acs-a")

    assert len(result) == 1
    assert result[0].name == "acs-a"


def test_filter_acs_instances_name_not_found() -> None:
    instances = [_make_instance("acs-a")]

    with pytest.raises(AppInterfaceSettingsError, match="not found"):
        AcsBaseApi.filter_acs_instances(instances, name="nonexistent")


def test_filter_acs_instances_none_found() -> None:
    with pytest.raises(AppInterfaceSettingsError, match="No ACS instances found"):
        AcsBaseApi.filter_acs_instances([])
