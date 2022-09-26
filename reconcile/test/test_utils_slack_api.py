import json
from collections import namedtuple
from typing import Union, Dict
from unittest.mock import call, patch, MagicMock

import httpretty
import pytest
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

import reconcile
from reconcile.utils.slack_api import (
    SlackApi,
    MAX_RETRIES,
    UserNotFoundException,
    SlackApiConfig,
    TIMEOUT,
)


@pytest.fixture
def slack_api(mocker):
    mock_secret_reader = mocker.patch.object(
        reconcile.utils.slack_api, "SecretReader", autospec=True
    )

    mock_slack_client = mocker.patch.object(
        reconcile.utils.slack_api, "WebClient", autospec=True
    )

    # autospec doesn't know about instance attributes
    mock_slack_client.return_value.retry_handlers = []

    token = {"path": "some/path", "field": "some-field"}
    slack_api = SlackApi(
        "some-workspace", token, reconcile.utils.slack_api.SecretReader()
    )

    SlackApiMock = namedtuple(
        "SlackApiMock", "client mock_secret_reader " "mock_slack_client"
    )

    return SlackApiMock(slack_api, mock_secret_reader, mock_slack_client)


def test_slack_api_config_defaults():
    slack_api_config = SlackApiConfig()

    assert slack_api_config.max_retries == MAX_RETRIES
    assert slack_api_config.timeout == TIMEOUT


def test_slack_api_config_from_dict():
    data = {
        "global": {"max_retries": 1, "timeout": 5},
        "methods": [
            {"name": "users.list", "args": '{"limit":1000}'},
            {"name": "conversations.list", "args": '{"limit":500}'},
        ],
    }

    slack_api_config = SlackApiConfig.from_dict(data)

    assert isinstance(slack_api_config, SlackApiConfig)

    assert slack_api_config.get_method_config("users.list") == {"limit": 1000}
    assert slack_api_config.get_method_config("conversations.list") == {"limit": 500}
    assert slack_api_config.get_method_config("doesntexist") is None

    assert slack_api_config.max_retries == 1
    assert slack_api_config.timeout == 5


def new_slack_response(data: Dict[str, Union[bool, str]]):
    return SlackResponse(
        client="",
        http_verb="",
        api_url="",
        req_args={},
        data=data,
        headers={},
        status_code=0,
    )


def test_instantiate_slack_api_with_config(mocker):
    """
    When SlackApiConfig is passed into SlackApi, the constructor shouldn't
    create a default configuration object.
    """
    mocker.patch.object(reconcile.utils.slack_api, "SecretReader", autospec=True)

    mock_slack_client = mocker.patch.object(
        reconcile.utils.slack_api, "WebClient", autospec=True
    )

    # autospec doesn't know about instance attributes
    mock_slack_client.return_value.retry_handlers = []

    config = SlackApiConfig()

    token = {"path": "some/path", "field": "some-field"}
    slack_api = SlackApi(
        "some-workspace", token, reconcile.utils.slack_api.SecretReader(), config
    )

    assert slack_api.config is config


def test__get_default_args(slack_api):
    """
    There shouldn't be any extra params passed to the client if config is
    unset.
    """
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        "channels": [],
        "response_metadata": {"next_cursor": ""},
    }

    slack_api.client._get("channels")

    assert slack_api.mock_slack_client.return_value.api_call.call_args == call(
        "conversations.list", http_verb="GET", params={"cursor": ""}
    )


def test__get_with_matching_method_config(slack_api):
    """Passing in a SlackApiConfig object with a matching method name."""
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        "channels": [],
        "response_metadata": {"next_cursor": ""},
    }

    api_config = SlackApiConfig()
    api_config.set_method_config("conversations.list", {"limit": 500})
    slack_api.client.config = api_config

    slack_api.client._get("channels")

    assert slack_api.mock_slack_client.return_value.api_call.call_args == call(
        "conversations.list", http_verb="GET", params={"limit": 500, "cursor": ""}
    )


def test__get_without_matching_method_config(slack_api):
    """Passing in a SlackApiConfig object without a matching method name."""
    slack_api.mock_slack_client.return_value.api_call.return_value = {
        "something": [],
        "response_metadata": {"next_cursor": ""},
    }

    api_config = SlackApiConfig()
    api_config.set_method_config("conversations.list", {"limit": 500})
    slack_api.client.config = api_config

    slack_api.client._get("something")

    assert slack_api.mock_slack_client.return_value.api_call.call_args == call(
        "something.list", http_verb="GET", params={"cursor": ""}
    )


def test__get_uses_cache(slack_api):
    """The API is never called when the results are already cached."""
    # Reset the mock to clear any calls during __init__
    slack_api.mock_slack_client.return_value.api_call.reset_mock()

    slack_api.client._results["channels"] = ["some", "data"]

    assert slack_api.client._get("channels") == ["some", "data"]
    slack_api.mock_slack_client.return_value.api_call.assert_not_called()


def test_chat_post_message(slack_api):
    """Don't raise an exception when the channel is set."""
    slack_api.client.channel = "some-channel"
    slack_api.client.chat_post_message("test")


def test_chat_post_message_missing_channel(slack_api):
    """Raises an exception when channel isn't set."""
    slack_api.client.channel = None
    with pytest.raises(ValueError):
        slack_api.client.chat_post_message("test")


def test_chat_post_message_channel_not_found(mocker, slack_api):
    slack_api.client.channel = "test"
    mock_join = mocker.patch(
        "reconcile.utils.slack_api.SlackApi.join_channel", autospec=True
    )
    nf_resp = new_slack_response({"ok": False, "error": "not_in_channel"})
    slack_api.mock_slack_client.return_value.chat_postMessage.side_effect = [
        SlackApiError("error", nf_resp),
        None,
    ]
    slack_api.client.chat_post_message("foo")
    assert slack_api.mock_slack_client.return_value.chat_postMessage.call_count == 2
    mock_join.assert_called_once()


def test_chat_post_message_ok(slack_api):
    slack_api.client.channel = "test"
    ok_resp = new_slack_response({"ok": True})
    slack_api.mock_slack_client.return_value.chat_postMessage.side_effect = ok_resp
    slack_api.client.chat_post_message("foo")
    slack_api.mock_slack_client.return_value.chat_postMessage.assert_called_once()


def test_chat_post_message_raises_other(mocker, slack_api):
    slack_api.client.channel = "test"
    err_resp = new_slack_response({"ok": False, "error": "no_text"})
    slack_api.mock_slack_client.return_value.chat_postMessage.side_effect = (
        SlackApiError("error", err_resp)
    )
    with pytest.raises(SlackApiError):
        slack_api.client.chat_post_message("foo")
    slack_api.mock_slack_client.return_value.chat_postMessage.assert_called_once()


def test_join_channel_missing_channel(slack_api):
    """Raises an exception when the channel is not set."""
    slack_api.client.channel = None
    with pytest.raises(ValueError):
        slack_api.client.join_channel()


@pytest.mark.parametrize("joined", [True, False])
def test_join_channel_already_joined(slack_api, mocker, joined):
    mocker.patch(
        "reconcile.utils.slack_api.SlackApi.get_channels_by_names",
        return_value={"123": "test", "456": "foo"},
    )
    slack_api.client.channel = "test"
    slack_response = MagicMock(SlackResponse)
    slack_response.data = {"channel": {"is_member": joined}}
    slack_api.mock_slack_client.return_value.conversations_info.return_value = (
        slack_response
    )
    slack_api.mock_slack_client.return_value.conversations_join.return_value = None
    slack_api.client.join_channel()
    slack_api.mock_slack_client.return_value.conversations_info.assert_called_once_with(
        channel="123"
    )
    if joined:
        slack_api.mock_slack_client.return_value.conversations_join.assert_not_called()
    else:
        slack_api.mock_slack_client.return_value.conversations_join.assert_called_once_with(
            channel="123"
        )


def test_create_usergroup(slack_api):
    slack_api.client.create_usergroup("ABCD")

    assert slack_api.mock_slack_client.return_value.usergroups_create.call_args == call(
        name="ABCD", handle="ABCD"
    )


def test_update_usergroup_users(slack_api):
    slack_api.client.update_usergroup_users("ABCD", ["USERA", "USERB"])

    assert (
        slack_api.mock_slack_client.return_value.usergroups_users_update.call_args
        == call(usergroup="ABCD", users=["USERA", "USERB"])
    )


@patch.object(SlackApi, "get_random_deleted_user", autospec=True)
def test_update_usergroup_users_empty_list(mock_get_deleted, slack_api):
    """Passing in an empty list supports removing all users from a group."""
    mock_get_deleted.return_value = "a-deleted-user"

    slack_api.client.update_usergroup_users("ABCD", [])

    assert (
        slack_api.mock_slack_client.return_value.usergroups_users_update.call_args
        == call(usergroup="ABCD", users=["a-deleted-user"])
    )


def test_get_user_id_by_name_user_not_found(slack_api):
    """
    Check that UserNotFoundException will be raised under expected conditions.
    """
    slack_api.mock_slack_client.return_value.users_lookupByEmail.side_effect = (
        SlackApiError("Some error message", {"error": "users_not_found"})
    )

    with pytest.raises(UserNotFoundException):
        slack_api.client.get_user_id_by_name("someuser", "redhat.com")


def test_get_user_id_by_name_reraise(slack_api):
    """
    Check that SlackApiError is re-raised when not otherwise handled as a user
    not found error.
    """
    slack_api.mock_slack_client.return_value.users_lookupByEmail.side_effect = (
        SlackApiError("Some error message", {"error": "internal_error"})
    )

    with pytest.raises(SlackApiError):
        slack_api.client.get_user_id_by_name("someuser", "redhat.com")


def test_update_usergroups_users_empty_no_raise(mocker, slack_api):
    """
    invalid_users errors shouldn't be raised because providing an empty
    list is actually removing users from the usergroup.
    """
    mocker.patch.object(SlackApi, "get_random_deleted_user", autospec=True)

    slack_api.mock_slack_client.return_value.usergroups_users_update.side_effect = (
        SlackApiError("Some error message", {"error": "invalid_users"})
    )

    slack_api.client.update_usergroup_users("ABCD", [])


def test_update_usergroups_users_raise(slack_api):
    """
    Any errors other than invalid_users should result in an exception being
    raised.
    """
    slack_api.mock_slack_client.return_value.usergroups_users_update.side_effect = (
        SlackApiError("Some error message", {"error": "internal_error"})
    )

    with pytest.raises(SlackApiError):
        slack_api.client.update_usergroup_users("ABCD", ["USERA"])


#
# Slack WebClient retry tests
#
# These tests are meant to ensure that the built-in retry functionality is
# working as expected in the Slack WebClient. This provides some verification
# that the handlers are configured properly, as well as testing the custom
# ServerErrorRetryHandler handler.
#


@httpretty.activate(allow_net_connect=False)
@patch("reconcile.utils.slack_api.SecretReader", autospec=True)
@patch("time.sleep", autospec=True)
def test_slack_api__client_throttle_raise(mock_sleep, mock_secret_reader):
    """Raise an exception if the max retries is exceeded."""
    httpretty.register_uri(
        httpretty.POST,
        "https://www.slack.com/api/users.list",
        adding_headers={"Retry-After": "1"},
        body=json.dumps({"ok": "false", "error": "ratelimited"}),
        status=429,
    )

    slack_client = SlackApi(
        "workspace",
        {"path": "some/path", "field": "some-field"},
        reconcile.utils.slack_api.SecretReader(),
        init_usergroups=False,
    )

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call("users.list")

    assert len(httpretty.latest_requests()) == MAX_RETRIES + 1


@httpretty.activate(allow_net_connect=False)
@patch("reconcile.utils.slack_api.SecretReader", autospec=True)
@patch("time.sleep", autospec=True)
def test_slack_api__client_throttle_doesnt_raise(mock_sleep, mock_secret_reader):
    """Don't raise an exception if the max retries aren't reached."""
    uri_args = (httpretty.POST, "https://www.slack.com/api/users.list")
    uri_kwargs_failure = {
        "adding_headers": {"Retry-After": "1"},
        "body": json.dumps({"ok": "false", "error": "ratelimited"}),
        "status": 429,
    }
    uri_kwargs_success = {"body": json.dumps({"ok": "true"}), "status": 200}

    # These are registered LIFO (3 failures and then 1 success)
    httpretty.register_uri(*uri_args, **uri_kwargs_success)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)

    slack_client = SlackApi(
        "workspace",
        {"path": "some/path", "field": "some-field"},
        reconcile.utils.slack_api.SecretReader(),
        init_usergroups=False,
    )

    slack_client._sc.api_call("users.list")

    assert len(httpretty.latest_requests()) == 4


@httpretty.activate(allow_net_connect=False)
@patch("reconcile.utils.slack_api.SecretReader", autospec=True)
@patch("time.sleep", autospec=True)
def test_slack_api__client_5xx_raise(mock_sleep, mock_secret_reader):
    """Raise an exception if the max retries is exceeded."""
    httpretty.register_uri(
        httpretty.POST,
        "https://www.slack.com/api/users.list",
        body=json.dumps({"ok": "false", "error": "internal_error"}),
        status=500,
    )

    slack_client = SlackApi(
        "workspace",
        {"path": "some/path", "field": "some-field"},
        reconcile.utils.slack_api.SecretReader(),
        init_usergroups=False,
    )

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call("users.list")

    assert len(httpretty.latest_requests()) == MAX_RETRIES + 1


@httpretty.activate(allow_net_connect=False)
@patch("reconcile.utils.slack_api.SecretReader", autospec=True)
@patch("time.sleep", autospec=True)
def test_slack_api__client_5xx_doesnt_raise(mock_sleep, mock_secret_reader):
    """Don't raise an exception if the max retries aren't reached."""
    uri_args = (httpretty.POST, "https://www.slack.com/api/users.list")
    uri_kwargs_failure = {
        "body": json.dumps({"ok": "false", "error": "internal_error"}),
        "status": 500,
    }
    uri_kwargs_success = {"body": json.dumps({"ok": "true"}), "status": 200}

    # These are registered LIFO (3 failures and then 1 success)
    httpretty.register_uri(*uri_args, **uri_kwargs_success)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)
    httpretty.register_uri(*uri_args, **uri_kwargs_failure)

    slack_client = SlackApi(
        "workspace",
        {"path": "some/path", "field": "some-field"},
        reconcile.utils.slack_api.SecretReader(),
        init_usergroups=False,
    )

    slack_client._sc.api_call("users.list")

    assert len(httpretty.latest_requests()) == 4


@httpretty.activate(allow_net_connect=False)
@patch("reconcile.utils.slack_api.SecretReader", autospec=True)
@patch("time.sleep", autospec=True)
def test_slack_api__client_dont_retry(mock_sleep, mock_secret_reader):
    """Don't retry client-side errors that aren't 429s."""
    httpretty.register_uri(
        httpretty.POST,
        "https://www.slack.com/api/users.list",
        body=json.dumps({"ok": "false", "error": "internal_error"}),
        status=401,
    )

    slack_client = SlackApi(
        "workspace",
        {"path": "some/path", "field": "some-field"},
        reconcile.utils.slack_api.SecretReader(),
        init_usergroups=False,
    )

    with pytest.raises(SlackApiError):
        slack_client._sc.api_call("users.list")

    assert len(httpretty.latest_requests()) == 1
