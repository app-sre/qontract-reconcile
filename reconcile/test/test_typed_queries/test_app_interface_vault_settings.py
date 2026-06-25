from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceVaultSettingsQueryData,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.exceptions import AppInterfaceSettingsError

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Mapping,
    )


def test_no_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., AppInterfaceVaultSettingsQueryData],
) -> None:
    data = gql_class_factory(AppInterfaceVaultSettingsQueryData, {"vault_settings": []})
    with pytest.raises(AppInterfaceSettingsError):
        get_app_interface_vault_settings(
            query_func=query_func(data.model_dump(by_alias=True))
        )


def test_multiple_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., AppInterfaceVaultSettingsQueryData],
) -> None:
    data = gql_class_factory(
        AppInterfaceVaultSettingsQueryData,
        {"vault_settings": [{"vault": True}, {"vault": False}]},
    )
    with pytest.raises(AppInterfaceSettingsError):
        get_app_interface_vault_settings(
            query_func=query_func(data.model_dump(by_alias=True))
        )


def test_get_vault_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., AppInterfaceVaultSettingsQueryData],
) -> None:
    data = gql_class_factory(
        AppInterfaceVaultSettingsQueryData, {"vault_settings": [{"vault": True}]}
    )
    vault_settings = get_app_interface_vault_settings(
        query_func=query_func(data.model_dump(by_alias=True))
    )
    assert vault_settings.vault
