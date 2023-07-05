from unittest.mock import (
    Mock,
    create_autospec,
)

import pytest
from jira import JIRA
from pytest_mock import MockerFixture

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


def test_create_with_jira_watcher_settings(
    mocker: MockerFixture,
    secret_reader: Mock,
    jira_board: dict,
):
    mocked_jira = mocker.patch("reconcile.utils.jira_client.JIRA", autospec=True)
    jira_watcher_settings = JiraWatcherSettingsV1(readTimeout=42, connectTimeout=43)

    jira_client = JiraClient.create(
        jira_board=jira_board,
        secret_reader=secret_reader,
        jira_watcher_settings=jira_watcher_settings,
    )

    assert jira_client.project == jira_board["name"]
    assert jira_client.jira == mocked_jira.return_value
    expected_server = jira_board["server"]["serverUrl"]
    expected_token = secret_reader.read.return_value
    expected_connect_timeout = jira_watcher_settings.connect_timeout
    expected_read_timeout = jira_watcher_settings.read_timeout
    mocked_jira.assert_called_once_with(
        expected_server,
        token_auth=expected_token,
        timeout=(expected_read_timeout, expected_connect_timeout),
    )


def test_create_with_defaults(
    mocker: MockerFixture,
    secret_reader: Mock,
    jira_board: dict,
):
    mocked_jira = mocker.patch("reconcile.utils.jira_client.JIRA", autospec=True)

    jira_client = JiraClient.create(
        jira_board=jira_board,
        secret_reader=secret_reader,
    )

    assert jira_client.project == jira_board["name"]
    assert jira_client.jira == mocked_jira.return_value
    expected_server = jira_board["server"]["serverUrl"]
    expected_token = secret_reader.read.return_value
    expected_connect_timeout = JiraClient.DEFAULT_CONNECT_TIMEOUT
    expected_read_timeout = JiraClient.DEFAULT_READ_TIMEOUT
    mocked_jira.assert_called_once_with(
        expected_server,
        token_auth=expected_token,
        timeout=(expected_read_timeout, expected_connect_timeout),
    )
