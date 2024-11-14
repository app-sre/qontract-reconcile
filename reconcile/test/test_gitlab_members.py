import copy
from typing import Any
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import (
    Group,
)
from pytest_mock import MockerFixture

from reconcile import gitlab_members
from reconcile.gitlab_members import (
    Action,
    Diff,
    GitLabGroup,
    GitlabUser,
    State,
    add_or_update_user,
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
        name="gitlab",
        description="gitlab",
        url="http://foobar.com",
        token=vault_secret,
        sslVerify=False,
        managedGroups=["group1", "group2"],
    )


@pytest.fixture()
def gitlab_groups_map() -> dict[str, Group]:
    return {
        "group1": create_autospec(Group, name="group1", id="123"),
        "group2": create_autospec(Group, name="group2", id="124"),
    }


@pytest.fixture()
def state(gitlab_groups_map: dict[str, Group]) -> State:
    return {
        "group1": GitLabGroup(
            members=[
                GitlabUser(
                    access_level="developer", user="user1", state="active", id="123"
                ),
                GitlabUser(
                    access_level="maintainer", user="user2", state="active", id="124"
                ),
            ],
            group=gitlab_groups_map.get("group1"),
        ),
        "group2": GitLabGroup(
            members=[
                GitlabUser(
                    access_level="developer", user="user3", state="active", id="125"
                ),
                GitlabUser(
                    access_level="maintainer", user="user4", state="active", id="126"
                ),
            ],
            group=gitlab_groups_map.get("group2"),
        ),
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
        tag_on_merge_requests=None,
    )


def test_gitlab_members_get_current_state(
    mocker: MockerFixture,
    instance: GitlabInstanceV1,
    state: State,
    gitlab_groups_map: dict[str, Group],
) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    gl_mock.get_group_members.side_effect = [
        [
            {
                "user": "user1",
                "access_level": "developer",
                "id": "123",
                "state": "active",
            },
            {
                "user": "user2",
                "access_level": "maintainer",
                "id": "124",
                "state": "active",
            },
        ],
        [
            {
                "user": "user3",
                "access_level": "developer",
                "id": "125",
                "state": "active",
            },
            {
                "user": "user4",
                "access_level": "maintainer",
                "id": "126",
                "state": "active",
            },
        ],
    ]
    assert (
        gitlab_members.get_current_state(instance, gl_mock, gitlab_groups_map) == state
    )


def test_gitlab_members_get_desired_state(
    mocker: MockerFixture,
    instance: GitlabInstanceV1,
    permissions: list[PermissionGitlabGroupMembershipV1],
    user: User,
    gitlab_groups_map: dict[str, Group],
) -> None:
    mock_pagerduty_map = mocker.create_autospec(PagerDutyMap)
    mock_pagerduty_map.get.return_value.get_pagerduty_users.return_value = [
        "pagerduty+foobar",
        "nobody",
        "nobody+foobar",
    ]
    assert gitlab_members.get_desired_state(
        instance, mock_pagerduty_map, permissions, gitlab_groups_map, [user]
    ) == {
        "group1": GitLabGroup(
            members=[GitlabUser(user="devtools-bot", access_level="owner")],
            group=gitlab_groups_map.get("group1"),
        ),
        "group2": GitLabGroup(
            members=[
                GitlabUser(user="devtools-bot", access_level="owner"),
                GitlabUser(user="user1", access_level="owner"),
                GitlabUser(user="user2", access_level="owner"),
                GitlabUser(user="user3", access_level="owner"),
                GitlabUser(user="user4", access_level="owner"),
                GitlabUser(user="another-bot", access_level="owner"),
            ],
            group=gitlab_groups_map.get("group2"),
        ),
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


def test_gitlab_members_subtract_states_add(
    state: State, gitlab_groups_map: dict[str, Group]
) -> None:
    current_state = copy.deepcopy(state)
    # enforce add users to groups
    current_state["group2"].members = [
        GitlabUser(access_level="maintainer", user="otherone", state="active", id="121")
    ]
    del current_state["group1"].members[1]

    desired_state = state
    assert gitlab_members.subtract_states(
        desired_state, current_state, Action.add_user_to_group
    ) == [
        Diff(
            action=Action.add_user_to_group,
            group=gitlab_groups_map.get("group1"),
            user=GitlabUser(
                user="user2", access_level="maintainer", id="124", state="active"
            ),
        ),
        Diff(
            action=Action.add_user_to_group,
            group=gitlab_groups_map.get("group2"),
            user=GitlabUser(
                user="user3", access_level="developer", id="125", state="active"
            ),
        ),
        Diff(
            action=Action.add_user_to_group,
            group=gitlab_groups_map.get("group2"),
            user=GitlabUser(
                user="user4", access_level="maintainer", id="126", state="active"
            ),
        ),
    ]


def test_gitlab_members_subtract_states_remove(
    state: State, gitlab_groups_map: dict[str, Group]
) -> None:
    current_state = copy.deepcopy(state)
    # enforce remove user from group
    current_state["group2"].members = [
        GitlabUser(access_level="maintainer", user="otherone", state="active", id="121")
    ]

    desired_state = state
    assert gitlab_members.subtract_states(
        current_state, desired_state, Action.remove_user_from_group
    ) == [
        Diff(
            action=Action.remove_user_from_group,
            group=gitlab_groups_map.get("group2"),
            user=GitlabUser(
                access_level="maintainer", user="otherone", state="active", id="121"
            ),
        )
    ]


def test_gitlab_members_check_access_no_changes(state: State) -> None:
    # pylint: disable-next=use-implicit-booleaness-not-comparison # for better readability
    assert gitlab_members.check_access(state, state) == []


def test_gitlab_members_check_access(
    state: State, gitlab_groups_map: dict[str, Group]
) -> None:
    current_state = copy.deepcopy(state)
    # enforce access change
    current_state["group1"].members[0].access_level = "owner"
    desired_state = state
    assert gitlab_members.check_access(current_state, desired_state) == [
        Diff(
            action=Action.change_access,
            group=gitlab_groups_map.get("group1"),
            user=GitlabUser(
                access_level="developer", user="user1", state="active", id="123"
            ),
        ),
    ]


def test_gitlab_members_calculate_diff_changes(
    state: State, gitlab_groups_map: dict[str, Group]
) -> None:
    current_state = copy.deepcopy(state)
    # enforce remove user from group
    current_state["group2"].members = [
        GitlabUser(access_level="maintainer", user="otherone", id="121", state="active")
    ]
    # enforce add user to group
    del current_state["group1"].members[1]
    # enforce access change
    current_state["group1"].members[0].access_level = "owner"
    desired_state = state
    assert gitlab_members.calculate_diff(current_state, desired_state) == [
        Diff(
            action=Action.add_user_to_group,
            group=gitlab_groups_map.get("group1"),
            user=GitlabUser(
                access_level="maintainer", user="user2", state="active", id="124"
            ),
        ),
        Diff(
            action=Action.add_user_to_group,
            group=gitlab_groups_map.get("group2"),
            user=GitlabUser(
                access_level="developer", user="user3", state="active", id="125"
            ),
        ),
        Diff(
            action=Action.add_user_to_group,
            group=gitlab_groups_map.get("group2"),
            user=GitlabUser(
                access_level="maintainer", user="user4", state="active", id="126"
            ),
        ),
        Diff(
            action=Action.remove_user_from_group,
            group=gitlab_groups_map.get("group2"),
            user=GitlabUser(
                access_level="maintainer", user="otherone", id="121", state="active"
            ),
        ),
        Diff(
            action=Action.change_access,
            group=gitlab_groups_map.get("group1"),
            user=GitlabUser(
                access_level="developer", user="user1", state="active", id="123"
            ),
        ),
    ]


def test_gitlab_members_act_add(
    mocker: MockerFixture, gitlab_groups_map: dict[str, Group]
) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    diff = Diff(
        action=Action.add_user_to_group,
        group=gitlab_groups_map.get("group2"),
        user=GitlabUser(
            access_level="maintainer", user="user4", state="active", id="126"
        ),
    )
    gitlab_members.act(diff, gl_mock)
    gl_mock.add_group_member.assert_called_once()
    gl_mock.remove_group_member.assert_not_called()
    gl_mock.change_access.assert_not_called()


def test_gitlab_members_act_remove(
    mocker: MockerFixture, gitlab_groups_map: dict[str, Group]
) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    diff = Diff(
        action=Action.remove_user_from_group,
        group=gitlab_groups_map.get("group2"),
        user=GitlabUser(
            access_level="maintainer", user="otherone", state="active", id="121"
        ),
    )
    gitlab_members.act(diff, gl_mock)
    gl_mock.add_group_member.assert_not_called()
    gl_mock.remove_group_member.assert_called_once()
    gl_mock.change_access.assert_not_called()


def test_gitlab_members_act_change(
    mocker: MockerFixture, gitlab_groups_map: dict[str, Group]
) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    diff = Diff(
        action=Action.change_access,
        group=gitlab_groups_map.get("group1"),
        user=GitlabUser(
            access_level="developer", user="user1", state="active", id="121"
        ),
    )
    gitlab_members.act(diff, gl_mock)
    gl_mock.add_group_member.assert_not_called()
    gl_mock.remove_group_member.assert_not_called()
    gl_mock.change_access.assert_called_once()


def test_add_or_update_user_add():
    grp = create_autospec(Group, name="t")
    group_members: State = {"t": GitLabGroup(members=[], group=grp)}
    gu = GitlabUser(user="u", access_level="owner", id="1234", state="active")
    add_or_update_user(group_members, "t", gu)
    assert group_members == {"t": GitLabGroup(members=[gu], group=grp)}


def test_add_or_update_user_update_higher():
    grp = create_autospec(Group, name="t")
    group_members: State = {"t": GitLabGroup(members=[], group=grp)}
    gu1 = GitlabUser(user="u", access_level="maintainer")
    gu2 = GitlabUser(user="u", access_level="owner")
    add_or_update_user(group_members, "t", gu1)
    add_or_update_user(group_members, "t", gu2)
    assert group_members == {"t": GitLabGroup(members=[gu2], group=grp)}


def test_add_or_update_user_update_lower():
    grp = create_autospec(Group, name="t")
    group_members: State = {"t": GitLabGroup(members=[], group=grp)}
    gu1 = GitlabUser(user="u", access_level="owner")
    gu2 = GitlabUser(user="u", access_level="maintainer")
    add_or_update_user(group_members, "t", gu1)
    add_or_update_user(group_members, "t", gu2)
    assert group_members == {"t": GitLabGroup(members=[gu1], group=grp)}
