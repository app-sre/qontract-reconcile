from unittest.mock import Mock

import pytest

from reconcile.gql_definitions.common.jira_settings import JiraWatcherSettingsV1
from reconcile.utils.jira_client import JiraClient


def test_create_secret_reader_and_settings(secret_reader: Mock) -> None:
    with pytest.raises(RuntimeError):
        JiraClient(
            jira_board={}, secret_reader=secret_reader, settings={"name": "test"}
        )


def test_create_jira_and_settings() -> None:
    jira_watcher_settings = JiraWatcherSettingsV1(connectTimeout=42, readTimeout=42)
    with pytest.raises(RuntimeError):
        JiraClient(
            jira_board={},
            jira_watcher_settings=jira_watcher_settings,
            settings={"name": "test"},
        )


def test_create_no_settings() -> None:
    with pytest.raises(RuntimeError):
        JiraClient(jira_board={})
