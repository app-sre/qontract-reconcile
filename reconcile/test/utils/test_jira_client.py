from unittest.mock import (
    Mock,
    create_autospec,
)

import pytest
from jira import JIRA

from reconcile.gql_definitions.common.jira_settings import JiraWatcherSettingsV1
from reconcile.utils.jira_client import JiraClient


@pytest.fixture
def jira_board() -> dict:
    return {
        "name": "test",
        "server": {
            "serverUrl": "test",
            "token": {},
        },
    }


def test_create_defaults(secret_reader: Mock, jira_board: dict) -> None:
    jira_api = create_autospec(spec=JIRA)
    jira_client = JiraClient(
        jira_board=jira_board, secret_reader=secret_reader, jira_api=jira_api
    )

    assert jira_client._connect_timeout == 60
    assert jira_client._read_timeout == 60
    assert jira_client._token_auth == "secret"


def test_create_with_settings(secret_reader: Mock, jira_board: dict) -> None:
    jira_api = create_autospec(spec=JIRA)
    jira_watcher_settings = JiraWatcherSettingsV1(connectTimeout=42, readTimeout=42)
    jira_client = JiraClient(
        jira_board=jira_board,
        secret_reader=secret_reader,
        jira_api=jira_api,
        jira_watcher_settings=jira_watcher_settings,
    )

    assert jira_client._connect_timeout == 42
    assert jira_client._read_timeout == 42
    assert jira_client._token_auth == "secret"


def test_create_secret_reader_and_settings(secret_reader: Mock) -> None:
    with pytest.raises(RuntimeError):
        JiraClient(
            jira_board={}, secret_reader=secret_reader, settings={"name": "test"}
        )


def test_create_jira_and_settings(secret_reader: Mock) -> None:
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
