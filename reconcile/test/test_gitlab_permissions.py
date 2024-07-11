from unittest.mock import MagicMock, create_autospec

import pytest
from gitlab.v4.objects import (
    CurrentUser,
    GroupMember,
    Project,
    ProjectMember,
    ProjectMemberAllManager,
)
from pytest_mock import MockerFixture

from reconcile import gitlab_permissions
from reconcile.utils.gitlab_api import GitLabApi


@pytest.fixture()
def mocked_queries(mocker: MockerFixture) -> MagicMock:
    queries = mocker.patch("reconcile.gitlab_permissions.queries")
    queries.get_gitlab_instance.return_value = {}
    queries.get_app_interface_settings.return_value = {}
    queries.get_repos.return_value = ["https://test-gitlab.com"]
    return queries


@pytest.fixture()
def mocked_gl() -> MagicMock:
    gl = create_autospec(GitLabApi)
    gl.server = "test_server"
    gl.user = create_autospec(CurrentUser)
    gl.user.username = "test_name"
    gl.user.id = 1234
    return gl


def test_run_share_with_members(
    mocked_queries: MagicMock, mocker: MockerFixture, mocked_gl: MagicMock
) -> None:
    mocker.patch("reconcile.gitlab_permissions.GitLabApi").return_value = mocked_gl
    mocked_gl.get_app_sre_group_users.return_value = [
        create_autospec(GroupMember, id=123, username="test_name2")
    ]
    mocker.patch(
        "reconcile.gitlab_permissions.get_feature_toggle_state"
    ).return_value = False
    mocked_gl.get_project_maintainers.return_value = ["test_name"]

    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.add_project_member.assert_called_once()


def test_run_share_with_group(
    mocked_queries: MagicMock, mocker: MockerFixture, mocked_gl: MagicMock
) -> None:
    mocker.patch("reconcile.gitlab_permissions.GitLabApi").return_value = mocked_gl
    mocker.patch(
        "reconcile.gitlab_permissions.get_feature_toggle_state"
    ).return_value = True
    mocked_gl.get_group_id_and_shared_projects.return_value = (
        1234,
        {"https://test.com": {"group_access_level": 30, "group_name": "app-sre"}},
    )
    mocked_gl.get_access_level.return_value = 40
    project = create_autospec(Project)
    project.members_all = create_autospec(ProjectMemberAllManager)
    project.members_all.get.return_value = create_autospec(
        ProjectMember, id=mocked_gl.user.id, access_level=40
    )
    mocked_gl.get_project.return_value = project
    mocked_gl.is_group_project_owner.return_value = False
    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.share_project_with_group.assert_called_once_with(
        project, group_id=1234, access_level=40
    )


def test_run_reshare_with_group(
    mocked_queries: MagicMock, mocker: MockerFixture, mocked_gl: MagicMock
) -> None:
    mocker.patch("reconcile.gitlab_permissions.GitLabApi").return_value = mocked_gl
    mocker.patch(
        "reconcile.gitlab_permissions.get_feature_toggle_state"
    ).return_value = True
    mocked_gl.get_group_id_and_shared_projects.return_value = (
        1234,
        {
            "https://test-gitlab.com": {
                "group_access_level": 30,
                "group_name": "app-sre",
            }
        },
    )
    mocked_gl.get_access_level.return_value = 40
    project = create_autospec(Project)
    project.members_all = create_autospec(ProjectMemberAllManager)
    project.members_all.get.return_value = create_autospec(
        ProjectMember, id=mocked_gl.user.id, access_level=40
    )
    mocked_gl.get_project.return_value = project
    mocked_gl.is_group_project_owner.return_value = False
    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.share_project_with_group.assert_called_once_with(
        project=project, group_id=1234, access_level=40, reshare=True
    )
