import copy
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile import gitlab_members
from reconcile.gitlab_members import (
    Action,
    Diff,
    GitlabUser,
    State,
    get_permissions,
)
from reconcile.gql_definitions.fragments.user import User
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.gitlab_members.gitlab_instances import GitlabInstanceV1
from reconcile.gql_definitions.gitlab_members.permissions import (
    PermissionGitlabGroupMembershipV1,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.pagerduty_api import PagerDutyMap


@pytest.fixture()
def instance(vault_secret: VaultSecret) -> GitlabInstanceV1:
    return GitlabInstanceV1(
        url="http://foobar.com",
        token=vault_secret,
        sslVerify=False,
        managedGroups=["group1", "group2"],
    )


@pytest.fixture()
def state() -> State:
    return {
        "group1": [
            GitlabUser(access_level="developer", user="user1"),
            GitlabUser(access_level="maintainer", user="user2"),
        ],
        "group2": [
            GitlabUser(access_level="developer", user="user3"),
            GitlabUser(access_level="maintainer", user="user4"),
        ],
    }


@pytest.fixture
def permissions() -> list[PermissionGitlabGroupMembershipV1]:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fxt.get_anymarkup("permissions.yml")

    fxt = Fixtures("gitlab_members")
    return get_permissions(q)


@pytest.fixture
def user() -> User:
    return User(
        org_username="org_username",
        slack_username="slack_username",
        github_username="github_username",
        name="name",
        pagerduty_username="pagerduty_username",
    )


def test_gitlab_members_get_current_state(
    mocker: MockerFixture, instance: GitlabInstanceV1, state: State
) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    gl_mock.get_group_members.side_effect = [
        [
            {"user": "user1", "access_level": "developer"},
            {"user": "user2", "access_level": "maintainer"},
        ],
        [
            {"user": "user3", "access_level": "developer"},
            {"user": "user4", "access_level": "maintainer"},
        ],
    ]
    assert gitlab_members.get_current_state(instance, gl_mock) == state


def test_gitlab_members_get_desired_state(
    mocker: MockerFixture,
    instance: GitlabInstanceV1,
    permissions: list[PermissionGitlabGroupMembershipV1],
    user: User,
) -> None:
    mock_pagerduty_map = mocker.create_autospec(PagerDutyMap)
    mock_pagerduty_map.get.return_value.get_pagerduty_users.return_value = [
        "pagerduty+foobar",
        "nobody",
        "nobody+foobar",
    ]
    assert gitlab_members.get_desired_state(
        instance, mock_pagerduty_map, permissions, [user]
    ) == {
        "group1": [GitlabUser(user="devtools-bot", access_level="owner")],
        "group2": [
            GitlabUser(user="devtools-bot", access_level="owner"),
            GitlabUser(user="user1", access_level="owner"),
            GitlabUser(user="user2", access_level="owner"),
            GitlabUser(user="user3", access_level="owner"),
            GitlabUser(user="user4", access_level="owner"),
            GitlabUser(user="another-bot", access_level="owner"),
        ],
    }


def test_gitlab_members_calculate_diff_no_changes(state: State) -> None:
    # pylint: disable-next=use-implicit-booleaness-not-comparison # for better readability
    assert gitlab_members.calculate_diff(state, state) == []


def test_gitlab_members_subtract_states_no_changes_add(state: State) -> None:
    # pylint: disable-next=use-implicit-booleaness-not-comparison # for better readability
    assert gitlab_members.subtract_states(state, state, Action.add_user_to_group) == []


def test_gitlab_members_subtract_states_no_changes_remove(state: State) -> None:
    # pylint: disable=use-implicit-booleaness-not-comparison # for better readability
    assert (
        gitlab_members.subtract_states(state, state, Action.remove_user_from_group)
        == []
    )


def test_gitlab_members_subtract_states_add(state: State) -> None:
    current_state = copy.deepcopy(state)
    # enforce add users to groups
    current_state["group2"] = [GitlabUser(access_level="maintainer", user="otherone")]
    del current_state["group1"][1]

    desired_state = state
    assert gitlab_members.subtract_states(
        desired_state, current_state, Action.add_user_to_group
    ) == [
        Diff(
            action=Action.add_user_to_group,
            group="group1",
            user="user2",
            access_level="maintainer",
        ),
        Diff(
            action=Action.add_user_to_group,
            group="group2",
            user="user3",
            access_level="developer",
        ),
        Diff(
            action=Action.add_user_to_group,
            group="group2",
            user="user4",
            access_level="maintainer",
        ),
    ]


def test_gitlab_members_subtract_states_remove(state: State) -> None:
    current_state = copy.deepcopy(state)
    # enforce remove user from group
    current_state["group2"] = [GitlabUser(access_level="maintainer", user="otherone")]

    desired_state = state
    assert gitlab_members.subtract_states(
        current_state, desired_state, Action.remove_user_from_group
    ) == [
        Diff(
            action=Action.remove_user_from_group,
            group="group2",
            user="otherone",
            access_level="maintainer",
        )
    ]


def test_gitlab_members_check_access_no_changes(state: State) -> None:
    # pylint: disable-next=use-implicit-booleaness-not-comparison # for better readability
    assert gitlab_members.check_access(state, state) == []


def test_gitlab_members_check_access(state: State) -> None:
    current_state = copy.deepcopy(state)
    # enforce access change
    current_state["group1"][0].access_level = "owner"
    desired_state = state
    assert gitlab_members.check_access(current_state, desired_state) == [
        Diff(
            action=Action.change_access,
            group="group1",
            user="user1",
            access_level="developer",
        ),
    ]


def test_gitlab_members_calculate_diff_changes(state: State) -> None:
    current_state = copy.deepcopy(state)
    # enforce remove user from group
    current_state["group2"] = [GitlabUser(access_level="maintainer", user="otherone")]
    # enforce add user to group
    del current_state["group1"][1]
    # enforce access change
    current_state["group1"][0].access_level = "owner"
    desired_state = state
    assert gitlab_members.calculate_diff(current_state, desired_state) == [
        Diff(
            action=Action.add_user_to_group,
            group="group1",
            user="user2",
            access_level="maintainer",
        ),
        Diff(
            action=Action.add_user_to_group,
            group="group2",
            user="user3",
            access_level="developer",
        ),
        Diff(
            action=Action.add_user_to_group,
            group="group2",
            user="user4",
            access_level="maintainer",
        ),
        Diff(
            action=Action.remove_user_from_group,
            group="group2",
            user="otherone",
            access_level="maintainer",
        ),
        Diff(
            action=Action.change_access,
            group="group1",
            user="user1",
            access_level="developer",
        ),
    ]


def test_gitlab_members_act_add(mocker: MockerFixture) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    diff = Diff(
        action=Action.add_user_to_group,
        group="group2",
        user="user4",
        access_level="maintainer",
    )
    gitlab_members.act(diff, gl_mock)
    gl_mock.add_group_member.assert_called_once()
    gl_mock.remove_group_member.assert_not_called()
    gl_mock.change_access.assert_not_called()


def test_gitlab_members_act_remove(mocker: MockerFixture) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    diff = Diff(
        action=Action.remove_user_from_group,
        group="group2",
        user="otherone",
        access_level="maintainer",
    )
    gitlab_members.act(diff, gl_mock)
    gl_mock.add_group_member.assert_not_called()
    gl_mock.remove_group_member.assert_called_once()
    gl_mock.change_access.assert_not_called()


def test_gitlab_members_act_change(mocker: MockerFixture) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    diff = Diff(
        action=Action.change_access,
        group="group1",
        user="user1",
        access_level="developer",
    )
    gitlab_members.act(diff, gl_mock)
    gl_mock.add_group_member.assert_not_called()
    gl_mock.remove_group_member.assert_not_called()
    gl_mock.change_access.assert_called_once()
