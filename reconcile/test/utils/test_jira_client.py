from unittest.mock import Mock

import pytest
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


def test_create_defaults(
    secret_reader: Mock,
    jira_board: dict,
    mocker: MockerFixture,
) -> None:
    mocked_jira = mocker.patch("reconcile.utils.jira_client.JIRA")
    expected_server = jira_board["server"]["serverUrl"]
    expected_token_auth = secret_reader.read.return_value
    expected_read_timeout = 60
    expected_connect_timeout = 60

    jira_client = JiraClient(jira_board=jira_board, secret_reader=secret_reader)

    assert jira_client.jira == mocked_jira.return_value
    mocked_jira.assert_called_once_with(
        expected_server,
        token_auth=expected_token_auth,
        timeout=(expected_read_timeout, expected_connect_timeout),
    )


def test_create_with_settings(
    secret_reader: Mock,
    jira_board: dict,
    mocker: MockerFixture,
) -> None:
    mocked_jira = mocker.patch("reconcile.utils.jira_client.JIRA")
    jira_watcher_settings = JiraWatcherSettingsV1(connectTimeout=42, readTimeout=43)
    expected_server = jira_board["server"]["serverUrl"]
    expected_token_auth = secret_reader.read.return_value
    expected_read_timeout = jira_watcher_settings.read_timeout
    expected_connect_timeout = jira_watcher_settings.connect_timeout

    jira_client = JiraClient(
        jira_board=jira_board,
        secret_reader=secret_reader,
        jira_watcher_settings=jira_watcher_settings,
    )

    assert jira_client.jira == mocked_jira.return_value
    mocked_jira.assert_called_once_with(
        expected_server,
        token_auth=expected_token_auth,
        timeout=(expected_read_timeout, expected_connect_timeout),
    )
