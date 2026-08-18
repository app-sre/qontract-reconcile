from __future__ import annotations

from unittest.mock import MagicMock

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
            path="secret/path", field="token", version=None, format=None
        ),
        authProvider=AcsInstanceAuthProviderV1(name="sso", id="auth-id"),
    )


def test_get_acs_instances_returns_all() -> None:
    instances = [_make_instance("acs-a"), _make_instance("acs-b")]
    mock_query = MagicMock(
        return_value={"instances": [i.model_dump(by_alias=True) for i in instances]}
    )

    result = AcsBaseApi.get_acs_instances(mock_query)

    assert len(result) == 2
    assert {i.name for i in result} == {"acs-a", "acs-b"}


def test_get_acs_instances_filters_by_name() -> None:
    instances = [_make_instance("acs-a"), _make_instance("acs-b")]
    mock_query = MagicMock(
        return_value={"instances": [i.model_dump(by_alias=True) for i in instances]}
    )

    result = AcsBaseApi.get_acs_instances(mock_query, name="acs-a")

    assert len(result) == 1
    assert result[0].name == "acs-a"


def test_get_acs_instances_name_not_found() -> None:
    instances = [_make_instance("acs-a")]
    mock_query = MagicMock(
        return_value={"instances": [i.model_dump(by_alias=True) for i in instances]}
    )

    with pytest.raises(AppInterfaceSettingsError, match="not found"):
        AcsBaseApi.get_acs_instances(mock_query, name="nonexistent")


def test_get_acs_instances_none_found() -> None:
    mock_query = MagicMock(return_value={"instances": None})

    with pytest.raises(AppInterfaceSettingsError, match="No ACS instances found"):
        AcsBaseApi.get_acs_instances(mock_query)
