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


def test_create_api_and_settings() -> None:
    with pytest.raises(RuntimeError):
        JiraClient(
            jira_board={},
            jira_api=create_autospec(spec=JIRA),
            settings={"name": "test"},
        )


def test_create_no_api_no_settings() -> None:
    with pytest.raises(RuntimeError):
        JiraClient(jira_board={})


def test_parameters(secret_reader: Mock, jira_board: dict):
    jira_watcher_settings = JiraWatcherSettingsV1(readTimeout=42, connectTimeout=43)
    parameters = JiraClient.parameters(
        jira_board=jira_board,
        secret_reader=secret_reader,
        jira_watcher_settings=jira_watcher_settings,
    )

    expected_server = jira_board["server"]["serverUrl"]
    expected_token = secret_reader.read.return_value
    expected_connect_timeout = jira_watcher_settings.connect_timeout
    expected_read_timeout = jira_watcher_settings.read_timeout

    assert parameters.connect_timeout == expected_connect_timeout
    assert parameters.read_timeout == expected_read_timeout
    assert parameters.token == expected_token
    assert parameters.server == expected_server


def test_default_parameters(secret_reader: Mock, jira_board: dict):
    parameters = JiraClient.parameters(
        jira_board=jira_board, secret_reader=secret_reader
    )

    expected_server = jira_board["server"]["serverUrl"]
    expected_token = secret_reader.read.return_value
    expected_connect_timeout = 60
    expected_read_timeout = 60

    assert parameters.connect_timeout == expected_connect_timeout
    assert parameters.read_timeout == expected_read_timeout
    assert parameters.token == expected_token
    assert parameters.server == expected_server
