import copy
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import create_autospec, call, patch

import pytest

import reconcile.slack_usergroups as integ
import reconcile.slack_base as slackbase
from reconcile.slack_usergroups import act
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.slack_api import SlackApi
from reconcile import queries

from .fixtures import Fixtures


@pytest.fixture
def base_state():
    desired_state = {
        "slack-workspace": {
            "usergroup-1": {
                "workspace": "slack-workspace",
                "usergroup": "usergroup-1",
                "usergroup_id": "USERGA",
                "users": {"USERA": "username"},
                "channels": {"CHANA": "channel"},
                "description": "Some description",
            }
        }
    }

    return desired_state


class TestSupportFunctions(TestCase):
    def test_get_slack_usernames_from_schedule_none(self):
        result = integ.get_slack_usernames_from_schedule(None)
        self.assertEqual(result, [])

    def test_get_slack_usernames_from_schedule(self):
        now = datetime.utcnow()
        schedule = {
            "schedule": [
                {
                    "start": (now - timedelta(hours=1)).strftime(integ.DATE_FORMAT),
                    "end": (now + timedelta(hours=1)).strftime(integ.DATE_FORMAT),
                    "users": [{"org_username": "user", "slack_username": "user"}],
                }
            ]
        }
        result = integ.get_slack_usernames_from_schedule(schedule)
        self.assertEqual(result, ["user"])

    def test_get_slack_username_org_username(self):
        user = {
            "org_username": "org",
            "slack_username": None,
        }
        result = integ.get_slack_username(user)
        self.assertEqual(result, "org")

    def test_get_slack_username_slack_username(self):
        user = {
            "org_username": "org",
            "slack_username": "slack",
        }
        result = integ.get_slack_username(user)
        self.assertEqual(result, "slack")

    def test_get_pagerduty_username_org_username(self):
        user = {
            "org_username": "org",
            "pagerduty_username": None,
        }
        result = integ.get_pagerduty_name(user)
        self.assertEqual(result, "org")

    def test_get_pagerduty_username_slack_username(self):
        user = {
            "org_username": "org",
            "pagerduty_username": "pd",
        }
        result = integ.get_pagerduty_name(user)
        self.assertEqual(result, "pd")

    @patch.object(slackbase, "SlackApi", autospec=True)
    @patch.object(queries, "get_app_interface_settings", autospec=True)
    @patch.object(queries, "get_permissions_for_slack_usergroup", autospec=True)
    def test_get_slack_map_return_expected(
        self, mock_get_permissions, mock_get_app_interface_settings, mock_slack_api
    ):
        mock_get_permissions.return_value = self.get_permissions_fixture()
        slack_api_mock = create_autospec(SlackApi)
        expected_slack_map = {
            "coreos": {
                "slack": slack_api_mock,
                "managed_usergroups": ["app-sre-team", "app-sre-ic"],
            }
        }
        result = integ.get_slack_map(SecretReader())
        mock_slack_api.assert_called_once()
        self.assertEqual(
            result["coreos"]["managed_usergroups"],
            expected_slack_map["coreos"]["managed_usergroups"],
        )
        self.assertIn("slack", result["coreos"])

    @staticmethod
    def get_permissions_fixture():
        fxt = Fixtures("slack_usergroups")
        permissions = fxt.get_anymarkup("permissions.yml")["permissions"]
        return [p for p in permissions if p["service"] == "slack-usergroup"]


def test_act_no_changes_detected(base_state):
    """No changes should be made when the states are identical."""

    current_state = base_state
    desired_state = base_state

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    slack_client_mock.update_usergroup.assert_not_called()
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_dryrun_no_changes_made(base_state):
    """No changes should be made when dryrun mode is enabled."""

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"]["users"] = {
        "USERB": "someotherusername"
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=True)

    slack_client_mock.update_usergroup.assert_not_called()
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_empty_current_state(base_state):
    """
    An empty current state should be able to be handled properly (watching for
    TypeErrors, etc).
    """

    current_state = {}
    desired_state = base_state

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    slack_client_mock.create_usergroup.return_value = "USERGA"

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.create_usergroup.call_args_list == [call("usergroup-1")]
    assert slack_client_mock.update_usergroup.call_args_list == [
        call("USERGA", ["CHANA"], "Some description")
    ]
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call("USERGA", ["USERA"])
    ]


def test_act_update_usergroup_users(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"]["users"] = {
        "USERB": "someotherusername",
        "USERC": "anotheruser",
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    slack_client_mock.update_usergroup.assert_not_called()
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call("USERGA", ["USERB", "USERC"])
    ]


def test_act_update_usergroup_channels(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"]["channels"] = {
        "CHANB": "someotherchannel"
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call("USERGA", ["CHANB"], "Some description")
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_update_usergroup_description(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"][
        "description"
    ] = "A different description"

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call("USERGA", ["CHANA"], "A different description")
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_update_usergroup_desc_and_channels(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"][
        "description"
    ] = "A different description"
    desired_state["slack-workspace"]["usergroup-1"]["channels"] = {
        "CHANB": "someotherchannel"
    }

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call("USERGA", ["CHANB"], "A different description")
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_add_new_usergroups(base_state):

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"].update(
        {
            "usergroup-2": {
                "workspace": "slack-workspace",
                "usergroup": "usergroup-2",
                "usergroup_id": "USERGB",
                "users": {"USERB": "userb", "USERC": "userc"},
                "channels": {"CHANB": "channelb", "CHANC": "channelc"},
                "description": "A new usergroup",
            }
        }
    )

    desired_state["slack-workspace"].update(
        {
            "usergroup-3": {
                "workspace": "slack-workspace",
                "usergroup": "usergroup-3",
                "usergroup_id": "USERGC",
                "users": {"USERF": "userf", "USERG": "userg"},
                "channels": {"CHANF": "channelf", "CHANG": "channelg"},
                "description": "Another new usergroup",
            }
        }
    )

    slack_client_mock = create_autospec(SlackApi)
    slack_map = {"slack-workspace": {"slack": slack_client_mock}}

    slack_client_mock.create_usergroup.side_effect = ["USERGB", "USERGC"]

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.create_usergroup.call_args_list == [
        call("usergroup-2"),
        call("usergroup-3"),
    ]

    assert slack_client_mock.update_usergroup.call_args_list == [
        call("USERGB", ["CHANB", "CHANC"], "A new usergroup"),
        call("USERGC", ["CHANF", "CHANG"], "Another new usergroup"),
    ]
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call("USERGB", ["USERB", "USERC"]),
        call("USERGC", ["USERF", "USERG"]),
    ]
