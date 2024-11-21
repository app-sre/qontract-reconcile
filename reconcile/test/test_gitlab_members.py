from typing import Any
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import (
    Group,
    GroupMember,
)
from pytest_mock import MockerFixture

from reconcile import gitlab_members
from reconcile.gitlab_members import (
    CurrentState,
    CurrentStateSpec,
    DesiredState,
    DesiredStateSpec,
    GitlabUser,
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
    group1 = create_autospec(Group, name="group1", id="123")
    group1.name = "group1"
    group2 = create_autospec(Group, name="group2", id="124")
    group2.name = "group2"
    return {
        "group1": group1,
        "group2": group2,
    }


@pytest.fixture()
def all_users() -> list[GroupMember]:
    user1 = create_autospec(GroupMember, username="user1", id="123", access_level=30)
    user2 = create_autospec(GroupMember, username="user2", id="124", access_level=40)
    user3 = create_autospec(GroupMember, username="user3", id="125", access_level=30)
    user4 = create_autospec(GroupMember, username="user4", id="126", access_level=40)
    return [user1, user2, user3, user4]


@pytest.fixture()
def current_state(all_users: list[GroupMember]) -> CurrentState:
    return {
        "group1": CurrentStateSpec(
            members={
                "user1": all_users[0],
                "user2": all_users[1],
            },
        ),
        "group2": CurrentStateSpec(
            members={
                "user3": all_users[2],
                "user4": all_users[3],
            },
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
    current_state: CurrentState,
    gitlab_groups_map: dict[str, Group],
    all_users: list[GroupMember],
) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    gl_mock.get_group_members.side_effect = [
        [
            all_users[0],
            all_users[1],
        ],
        [
            all_users[2],
            all_users[3],
        ],
    ]
    assert (
        gitlab_members.get_current_state(instance, gl_mock, gitlab_groups_map)
        == current_state
    )


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
        "group1": DesiredStateSpec(
            members={"devtools-bot": GitlabUser(user="devtools-bot", access_level=50)},
        ),
        "group2": DesiredStateSpec(
            members={
                "devtools-bot": GitlabUser(user="devtools-bot", access_level=50),
                "user1": GitlabUser(user="user1", access_level=50),
                "user2": GitlabUser(user="user2", access_level=50),
                "user3": GitlabUser(user="user3", access_level=50),
                "user4": GitlabUser(user="user4", access_level=50),
                "another-bot": GitlabUser(user="another-bot", access_level=50),
            },
        ),
    }


def test_gitlab_members_reconcile_gitlab_members(
    gitlab_groups_map: dict[str, Group],
    mocker: MockerFixture,
    all_users: list[GroupMember],
) -> None:
    gl_mock = mocker.create_autospec(GitLabApi)
    current_state: CurrentState = {
        "group1": CurrentStateSpec(
            members={
                "user1": all_users[0],
                "user3": all_users[2],
                "user4": all_users[3],
            },
        )
    }
    new_user = GitlabUser(user="new_user", access_level=40)
    desired_state: DesiredState = {
        "group1": DesiredStateSpec(
            members={
                "user1": GitlabUser(user="user1", access_level=30),
                "new_user": new_user,
                "user3": GitlabUser(user="user3", access_level=50),
            }
        )
    }
    group = gitlab_groups_map.get("group1")
    gitlab_members.reconcile_gitlab_members(
        current_state_spec=current_state.get("group1"),
        desired_state_spec=desired_state.get("group1"),
        group=group,
        dry_run=False,
        gl=gl_mock,
    )
    gl_mock.add_group_member.assert_called_once_with(group, new_user)
    gl_mock.change_access.assert_called_once_with(all_users[2], 50)
    gl_mock.remove_group_member.assert_called_once_with(group, all_users[3].id)


def test_add_or_update_user_add():
    desired_state_spec: DesiredStateSpec = DesiredStateSpec(members={})
    gu = GitlabUser(user="u", access_level=50, id="1234")
    add_or_update_user(desired_state_spec, gu)
    assert desired_state_spec == DesiredStateSpec(members={"u": gu})


def test_add_or_update_user_update_higher():
    desired_state_spec: DesiredStateSpec = DesiredStateSpec(members={})
    gu1 = GitlabUser(user="u", access_level=40)
    gu2 = GitlabUser(user="u", access_level=50)
    add_or_update_user(desired_state_spec, gu1)
    add_or_update_user(desired_state_spec, gu2)
    assert desired_state_spec == DesiredStateSpec(members={"u": gu2})


def test_add_or_update_user_update_lower():
    desired_state_spec: DesiredStateSpec = DesiredStateSpec(members={})
    gu1 = GitlabUser(user="u", access_level=50)
    gu2 = GitlabUser(user="u", access_level=40)
    add_or_update_user(desired_state_spec, gu1)
    add_or_update_user(desired_state_spec, gu2)
    assert desired_state_spec == DesiredStateSpec(members={"u": gu1})
