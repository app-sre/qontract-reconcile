from unittest.mock import create_autospec

import pytest
from jira import JIRA
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.jira_settings import JiraWatcherSettingsV1
from reconcile.utils.jira_client import JiraClient


def test_create_with_jira_watcher_settings(
    mocker: MockerFixture,
):
    mocked_jira = mocker.patch("reconcile.utils.jira_client.JIRA", autospec=True)
    jira_watcher_settings = JiraWatcherSettingsV1(readTimeout=42, connectTimeout=43)

    expected_server_url = "test_url"
    expected_token = "test_token"
    expected_project = "test_project"
    expected_connect_timeout = jira_watcher_settings.connect_timeout
    expected_read_timeout = jira_watcher_settings.read_timeout

    jira_client = JiraClient.create(
        server_url=expected_server_url,
        project_name=expected_project,
        token=expected_token,
        jira_watcher_settings=jira_watcher_settings,
    )

    assert jira_client.project == expected_project
    assert jira_client.jira == mocked_jira.return_value

    mocked_jira.assert_called_once_with(
        expected_server_url,
        token_auth=expected_token,
        timeout=(expected_read_timeout, expected_connect_timeout),
    )


def test_create_with_defaults(
    mocker: MockerFixture,
):
    mocked_jira = mocker.patch("reconcile.utils.jira_client.JIRA", autospec=True)

    expected_server_url = "test_url"
    expected_token = "test_token"
    expected_project = "test_project"
    expected_connect_timeout = JiraClient.DEFAULT_CONNECT_TIMEOUT
    expected_read_timeout = JiraClient.DEFAULT_READ_TIMEOUT

    jira_client = JiraClient.create(
        server_url=expected_server_url,
        project_name=expected_project,
        token=expected_token,
    )

    assert jira_client.project == expected_project
    assert jira_client.jira == mocked_jira.return_value

    mocked_jira.assert_called_once_with(
        expected_server_url,
        token_auth=expected_token,
        timeout=(expected_read_timeout, expected_connect_timeout),
    )
