from collections.abc import (
    Callable,
    Mapping,
)
from typing import Optional

import pytest

from reconcile.gql_definitions.common.jira_settings import JiraSettingsQueryData
from reconcile.typed_queries.jira_settings import (
    AppInterfaceSettingsError,
    get_jira_settings,
)
from reconcile.utils.gql import GqlApi


def test_no_settings(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., JiraSettingsQueryData],
) -> None:
    data = gql_class_factory(JiraSettingsQueryData, {})
    api = gql_api_builder(data.dict(by_alias=True))
    with pytest.raises(AppInterfaceSettingsError):
        get_jira_settings(gql_api=api)


def test_multiple_settings(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., JiraSettingsQueryData],
) -> None:
    data = gql_class_factory(JiraSettingsQueryData, {"jira_settings": [{}, {}]})
    api = gql_api_builder(data.dict(by_alias=True))
    with pytest.raises(AppInterfaceSettingsError):
        get_jira_settings(gql_api=api)


def test_exactly_one_setting(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., JiraSettingsQueryData],
) -> None:
    data = gql_class_factory(
        JiraSettingsQueryData,
        {"jira_settings": [{"jiraWatcher": {"readTimeout": 1, "connectTimeout": 2}}]},
    )
    api = gql_api_builder(data.dict(by_alias=True))
    jira_settings = get_jira_settings(gql_api=api)
    assert jira_settings.jira_watcher
    assert jira_settings.jira_watcher.connect_timeout == 2
    assert jira_settings.jira_watcher.read_timeout == 1
