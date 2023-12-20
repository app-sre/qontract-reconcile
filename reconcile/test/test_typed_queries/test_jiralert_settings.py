from collections.abc import Callable, Mapping

import pytest

from reconcile.gql_definitions.common.jiralert_settings import JiralertSettingsQueryData
from reconcile.typed_queries.jiralert_settings import get_jiralert_settings
from reconcile.utils.exceptions import AppInterfaceSettingsError


def test_jiralert_settings_no_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., JiralertSettingsQueryData],
) -> None:
    data = gql_class_factory(JiralertSettingsQueryData, {"settings": []})
    with pytest.raises(AppInterfaceSettingsError):
        get_jiralert_settings(query_func=query_func(data.dict(by_alias=True)))


def test_jiralert_settings_multiple_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., JiralertSettingsQueryData],
) -> None:
    data = gql_class_factory(
        JiralertSettingsQueryData,
        {
            "settings": [
                {
                    "jiralert": {
                        "defaultIssueType": "task",
                        "defaultReopenState": "new",
                    },
                },
                {
                    "jiralert": {
                        "defaultIssueType": "task",
                        "defaultReopenState": "new",
                    },
                },
            ]
        },
    )
    with pytest.raises(AppInterfaceSettingsError):
        get_jiralert_settings(query_func=query_func(data.dict(by_alias=True)))


def test_jiralert_settings_get_vault_settings(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., JiralertSettingsQueryData],
) -> None:
    data = gql_class_factory(
        JiralertSettingsQueryData,
        {
            "settings": [
                {
                    "jiralert": {
                        "defaultIssueType": "task",
                        "defaultReopenState": "new",
                    },
                },
            ]
        },
    )
    jiralert_settings = get_jiralert_settings(
        query_func=query_func(data.dict(by_alias=True))
    )
    assert jiralert_settings.default_issue_type == "task"
    assert jiralert_settings.default_reopen_state == "new"
