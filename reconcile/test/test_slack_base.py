import pytest

from reconcile.slack_base import (
    slackapi_from_slack_workspace,
    slackapi_from_permissions,
)


def create_api_config():
    return {
        "global": {"max_retries": 5, "timeout": 30},
        "methods": [
            {"name": "users.list", "args": '{"limit":123}'},
        ],
    }


@pytest.fixture
def slack_workspace():
    return {
        "workspace": {
            "name": "coreos",
            "integrations": [
                {
                    "name": "dummy",
                    "token": {
                        "path": "some/path",
                        "field": "bot_token",
                    },
                    "channel": "test",
                    "icon_emoji": "test_emoji",
                    "username": "foo",
                },
            ],
            "api_client": create_api_config(),
        }
    }


@pytest.fixture
def unleash_slack_workspace():
    return {
        "workspace": {
            "name": "coreos",
            "integrations": [
                {
                    "name": "unleash-watcher",
                    "token": {
                        "path": "some/path",
                        "field": "bot_token",
                    },
                },
            ],
            "api_client": create_api_config(),
        },
        "channel": "test",
        "icon_emoji": "unleash",
        "username": "test",
    }


@pytest.fixture
def permissions_workspace():
    return {
        "workspace": {
            "name": "coreos",
            "token": {
                "path": "some/path",
                "field": "bot_token",
            },
            "api_client": create_api_config(),
            "managedUsergroups": ["foo"],
        }
    }


@pytest.fixture
def patch_secret_reader(mocker):
    return mocker.patch(
        "reconcile.utils.secret_reader.SecretReader.read",
        return_value="secret",
        autospec=True,
    )


@pytest.fixture
def patch__initiate_usergroups(mocker):
    return mocker.patch(
        "reconcile.utils.slack_api.SlackApi._initiate_usergroups", autospec=True
    )


def test_slack_workspace_raises():
    with pytest.raises(ValueError):
        slackapi_from_slack_workspace({}, {}, "foo")


def test_slack_workspace_ok(
    patch_secret_reader, patch__initiate_usergroups, slack_workspace
):
    slack_api = slackapi_from_slack_workspace(slack_workspace, {}, "dummy")
    patch_secret_reader.assert_called_once()
    patch__initiate_usergroups.assert_called_once()
    assert slack_api.channel == "test"
    assert slack_api.chat_kwargs["icon_emoji"] == "test_emoji"
    assert slack_api.config.get_method_config("users.list") == {"limit": 123}


def test_slack_workspace_channel_overwrite(
    patch_secret_reader, patch__initiate_usergroups, slack_workspace
):
    slack_api = slackapi_from_slack_workspace(
        slack_workspace, {}, "dummy", channel="foo"
    )
    assert slack_api.channel == "foo"


def test_unleash_workspace_ok(
    patch_secret_reader, patch__initiate_usergroups, unleash_slack_workspace
):
    slack_api = slackapi_from_slack_workspace(
        unleash_slack_workspace, {}, "unleash-watcher"
    )
    patch_secret_reader.assert_called_once()
    patch__initiate_usergroups.assert_called_once()
    assert slack_api.channel == "test"
    assert slack_api.chat_kwargs["icon_emoji"] == "unleash"
    assert slack_api.config.get_method_config("users.list") == {"limit": 123}


def test_slack_workspace_no_init(
    patch_secret_reader, patch__initiate_usergroups, slack_workspace
):
    slackapi_from_slack_workspace(slack_workspace, {}, "dummy", init_usergroups=False)
    patch__initiate_usergroups.assert_not_called()


def test_permissions_workspace(
    patch_secret_reader, patch__initiate_usergroups, permissions_workspace
):
    slack_api = slackapi_from_permissions(permissions_workspace, {})
    patch_secret_reader.assert_called_once()
    patch__initiate_usergroups.assert_called_once()

    assert slack_api.channel is None
    assert slack_api.config.get_method_config("users.list") == {"limit": 123}
