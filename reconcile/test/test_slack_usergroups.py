import copy
from collections.abc import (
    Iterable,
    Sequence,
)
from datetime import (
    datetime,
    timedelta,
)
from typing import Any
from unittest.mock import (
    Mock,
    call,
    create_autospec,
)

import pytest

import reconcile.slack_base as slackbase
import reconcile.slack_usergroups as integ
from reconcile.gql_definitions.fragments.user import User
from reconcile.gql_definitions.slack_usergroups.permissions import (
    PagerDutyInstanceV1,
    PagerDutyTargetV1,
    PermissionSlackUsergroupV1,
    ScheduleEntryV1,
)
from reconcile.slack_usergroups import (
    SlackMap,
    SlackObject,
    SlackState,
    State,
    WorkspaceSpec,
    act,
    query_permissions,
)
from reconcile.utils import repo_owners
from reconcile.utils.github_api import GithubApi
from reconcile.utils.pagerduty_api import PagerDutyMap
from reconcile.utils.slack_api import SlackApi

from .fixtures import Fixtures


@pytest.fixture
def base_state():
    state = SlackState(
        {
            "slack-workspace": {
                "usergroup-1": State(
                    workspace="slack-workspace",
                    usergroup="usergroup-1",
                    usergroup_id="USERGA",
                    users={SlackObject(name="username", pk="USERA")},
                    channels={SlackObject(name="channelname", pk="CHANA")},
                    description="Some description",
                )
            }
        }
    )

    return state


@pytest.fixture
def user() -> User:
    return User(
        org_username="org",
        slack_username="slack",
        github_username="github",
        name="name",
        pagerduty_username="pagerduty",
    )


@pytest.fixture
def permissions() -> list[PermissionSlackUsergroupV1]:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fxt.get_anymarkup("permissions.yml")

    fxt = Fixtures("slack_usergroups")
    return query_permissions(q)


@pytest.fixture
def slack_client_mock() -> SlackApi:
    return create_autospec(SlackApi)


@pytest.fixture
def slack_map(slack_client_mock: Mock) -> SlackMap:
    return {
        "slack-workspace": WorkspaceSpec(
            slack=slack_client_mock, managed_usergroups=[]
        ),
        "coreos": WorkspaceSpec(slack=slack_client_mock, managed_usergroups=[]),
    }


def test_query_permissions(permissions: Sequence[PermissionSlackUsergroupV1]) -> None:
    assert len(permissions) == 2
    p = permissions[0]
    assert p.channels and len(p.channels) == 2
    assert p.roles and p.roles[0].users == []

    p = permissions[1]
    assert p.roles and p.roles[0].users and p.roles[0].users[0].name == "Rafael"


def test_get_slack_usernames_from_schedule_none() -> None:
    result = integ.get_slack_usernames_from_schedule([])
    assert not result


def test_get_slack_usernames_from_schedule(user: User) -> None:
    now = datetime.utcnow()
    schedule = ScheduleEntryV1(
        start=(now - timedelta(hours=1)).strftime(integ.DATE_FORMAT),
        end=(now + timedelta(hours=1)).strftime(integ.DATE_FORMAT),
        users=[user],
    )
    result = integ.get_slack_usernames_from_schedule([schedule])
    assert result == [user.slack_username]


def test_get_slack_username_org_username(user: User) -> None:
    user.slack_username = None
    result = integ.get_slack_username(user)
    assert result == user.org_username


def test_get_slack_username_slack_username(user: User) -> None:
    result = integ.get_slack_username(user)
    assert result == user.slack_username


def test_get_pagerduty_username_org_username(user: User) -> None:
    user.pagerduty_username = None
    result = integ.get_pagerduty_name(user)
    assert result == user.org_username


def test_get_pagerduty_username_slack_username(user: User) -> None:
    result = integ.get_pagerduty_name(user)
    assert result == user.pagerduty_username


def test_get_usernames_from_pagerduty(user: User) -> None:
    pagerduties = [
        PagerDutyTargetV1(
            name="app-sre-pagerduty-primary-oncall",
            instance=PagerDutyInstanceV1(name="redhat"),
            scheduleID="PHS3079",
            escalationPolicyID=None,
        )
    ]
    mock_pagerduty_map = create_autospec(PagerDutyMap)
    mock_pagerduty_map.get.return_value.get_pagerduty_users.return_value = [
        "pagerduty+foobar",
        "nobody",
        "nobody+foobar",
    ]
    result = integ.get_usernames_from_pagerduty(
        pagerduties=pagerduties,
        users=[user],
        usergroup="usergroup",
        pagerduty_map=mock_pagerduty_map,
    )
    assert result == [user.slack_username]


def test_get_slack_usernames_from_owners(mocker: Mock, user: User) -> None:
    mocker.patch(
        "reconcile.slack_usergroups.get_git_api"
    ).return_value = create_autospec(GithubApi)
    mock_repo_owner = create_autospec(repo_owners.RepoOwners)
    mock_repo_owner.return_value.get_root_owners.return_value = {
        "approvers": ["approver1"],
        "reviewers": ["github"],  # <- the test user
    }
    result = integ.get_slack_usernames_from_owners(
        owners_from_repo=["https://github.com/owner/repo"],
        users=[user],
        usergroup="usergroup",
        repo_owner_class=mock_repo_owner,
    )
    assert result == [user.slack_username]


def test_get_desired_state(
    mocker: Mock,
    permissions: Sequence[PermissionSlackUsergroupV1],
    slack_map: SlackMap,
    slack_client_mock: Mock,
    user: User,
) -> None:
    mocker.patch(
        "reconcile.slack_usergroups.get_usernames_from_pagerduty"
    ).return_value = ["user1"]
    mocker.patch(
        "reconcile.slack_usergroups.get_slack_usernames_from_owners"
    ).return_value = ["repo-user"]
    mock_pagerduty_map = create_autospec(PagerDutyMap)
    slack_client_mock.get_usergroup_id.return_value = "ugid"
    result = integ.get_desired_state(
        slack_map,
        mock_pagerduty_map,
        permissions[1:],
        [user],
        desired_workspace_name=None,
        desired_usergroup_name=None,
    )
    assert slack_client_mock.get_users_by_names.call_args_list == [
        call(["repo-user", "slack_username", "user1"]),
    ]
    assert slack_client_mock.get_channels_by_names.call_args_list == [
        call(["sd-sre-platform", "sre-operators"])
    ]

    assert result == {
        "coreos": {
            "saas-osd-operators": State(
                workspace="coreos",
                usergroup="saas-osd-operators",
                description="SREP managed-cluster-config owners (managed via app-interface)",
                users=set(),
                channels=set(),
                usergroup_id="ugid",
            )
        }
    }


def test_get_slack_map_return_expected(
    mocker: Mock, permissions: Iterable[PermissionSlackUsergroupV1]
) -> None:
    mock_slack_api = mocker.patch.object(slackbase, "SlackApi", autospec=True)
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.return_value.read.return_value = "secret"

    result = integ.get_slack_map(mock_secretreader, permissions)
    mock_slack_api.assert_called_once()
    # just one workspace in the permissions
    assert len(result) == 1
    assert isinstance(result["coreos"].slack, SlackApi)
    assert result["coreos"].managed_usergroups == [
        "app-sre-team",
        "app-sre-ic",
        "backplane-team",
    ]


def test_act_no_changes_detected(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:
    """No changes should be made when the states are identical."""
    current_state = base_state
    desired_state = base_state

    act(current_state, desired_state, slack_map, dry_run=False)

    slack_client_mock.update_usergroup.assert_not_called()
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_dryrun_no_changes_made(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:
    """No changes should be made when dryrun mode is enabled."""

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"].users = {
        SlackObject(name="foo", pk="bar")
    }

    act(current_state, desired_state, slack_map, dry_run=True)

    slack_client_mock.update_usergroup.assert_not_called()
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_empty_current_state(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:
    """
    An empty current state should be able to be handled properly (watching for
    TypeErrors, etc).
    """

    current_state: SlackState = {}
    desired_state = base_state

    slack_client_mock.create_usergroup.return_value = "USERGA"

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.create_usergroup.call_args_list == [call("usergroup-1")]
    assert slack_client_mock.update_usergroup.call_args_list == [
        call(id="USERGA", channels_list=["CHANA"], description="Some description")
    ]
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call(id="USERGA", users_list=["USERA"])
    ]


def test_act_update_usergroup_users(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"].users = {
        SlackObject(name="someotherusername", pk="USERB"),
        SlackObject(name="anotheruser", pk="USERC"),
    }

    act(current_state, desired_state, slack_map, dry_run=False)

    slack_client_mock.update_usergroup.assert_not_called()
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call(id="USERGA", users_list=["USERB", "USERC"])
    ]


def test_act_update_usergroup_channels(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-1"].channels = {
        SlackObject(pk="CHANB", name="someotherchannel")
    }

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call(id="USERGA", channels_list=["CHANB"], description="Some description")
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_update_usergroup_description(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"][
        "usergroup-1"
    ].description = "A different description"

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call(
            id="USERGA", channels_list=["CHANA"], description="A different description"
        )
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_update_usergroup_desc_and_channels(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"][
        "usergroup-1"
    ].description = "A different description"
    desired_state["slack-workspace"]["usergroup-1"].channels = {
        SlackObject(pk="CHANB", name="someotherchannel")
    }

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.update_usergroup.call_args_list == [
        call(
            id="USERGA", channels_list=["CHANB"], description="A different description"
        )
    ]
    slack_client_mock.update_usergroup_users.assert_not_called()


def test_act_add_new_usergroups(
    base_state: SlackState, slack_map: SlackMap, slack_client_mock: Mock
) -> None:

    current_state = base_state
    desired_state = copy.deepcopy(base_state)

    desired_state["slack-workspace"]["usergroup-2"] = State(
        workspace="slack-workspace",
        usergroup="usergroup-2",
        usergroup_id="USERGB",
        users=[
            SlackObject(pk="USERB", name="userb"),
            SlackObject(pk="USERC", name="userc"),
        ],
        channels=[
            SlackObject(pk="CHANB", name="channelb"),
            SlackObject(pk="CHANC", name="channelc"),
        ],
        description="A new usergroup",
    )

    desired_state["slack-workspace"]["usergroup-3"] = State(
        workspace="slack-workspace",
        usergroup="usergroup-3",
        usergroup_id="USERGC",
        users=[
            SlackObject(pk="USERF", name="userf"),
            SlackObject(pk="USERG", name="userg"),
        ],
        channels=[
            SlackObject(pk="CHANF", name="channelf"),
            SlackObject(pk="CHANG", name="channelg"),
        ],
        description="Another new usergroup",
    )
    slack_client_mock.create_usergroup.side_effect = ["USERGB", "USERGC"]

    act(current_state, desired_state, slack_map, dry_run=False)

    assert slack_client_mock.create_usergroup.call_args_list == [
        call("usergroup-2"),
        call("usergroup-3"),
    ]

    assert slack_client_mock.update_usergroup.call_args_list == [
        call(
            id="USERGB", channels_list=["CHANB", "CHANC"], description="A new usergroup"
        ),
        call(
            id="USERGC",
            channels_list=["CHANF", "CHANG"],
            description="Another new usergroup",
        ),
    ]
    assert slack_client_mock.update_usergroup_users.call_args_list == [
        call(id="USERGB", users_list=["USERB", "USERC"]),
        call(id="USERGC", users_list=["USERF", "USERG"]),
    ]
