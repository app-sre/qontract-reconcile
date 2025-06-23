from unittest.mock import MagicMock, create_autospec

import pytest
from gitlab.v4.objects import (
    CurrentUser,
    Group,
    GroupMember,
    GroupProjectManager,
    Project,
    ProjectMember,
    ProjectMemberAllManager,
    SharedProject,
    SharedProjectManager,
)
from pytest_mock import MockerFixture

from reconcile import gitlab_permissions
from reconcile.utils.gitlab_api import GitLabApi

GITLAB_TEST_URL = "https://test-gitlab.com/my/repo"


@pytest.fixture()
def mocked_queries(mocker: MockerFixture) -> MagicMock:
    queries = mocker.patch("reconcile.gitlab_permissions.queries")
    queries.get_gitlab_instance.return_value = {}
    queries.get_app_interface_settings.return_value = {}
    queries.get_repos.return_value = [GITLAB_TEST_URL]
    queries.get_gitlab_instance.return_value = {
        "url": "https://test-gitlab.com",
        "projectRequests": [
            {
                "group": "my",
                "projects": [
                    "repo",
                ],
            },
        ],
    }
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
    group = create_autospec(Group, id=1234)
    group.name = "app-sre"
    group.projects = create_autospec(GroupProjectManager)
    group.shared_projects = create_autospec(SharedProjectManager)
    mocked_gl.get_group.return_value = group
    mocked_gl.get_access_level.return_value = 40
    project = create_autospec(Project, web_url="https://test.com")
    project.members_all = create_autospec(ProjectMemberAllManager)
    project.members_all.get.return_value = create_autospec(
        ProjectMember, id=mocked_gl.user.id, access_level=40
    )
    mocked_gl.get_project.return_value = project
    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.share_project_with_group.assert_called_once_with(
        project, group_id=1234, access_level=40
    )


def test_run_managed_repo_not_created_yet(
    mocked_queries: MagicMock, mocker: MockerFixture, mocked_gl: MagicMock
) -> None:
    """
    Repos that are managed in app-interface might not have been created yet by our automation.
    We should skip those repos.
    """
    mocker.patch("reconcile.gitlab_permissions.GitLabApi").return_value = mocked_gl
    mocker.patch(
        "reconcile.gitlab_permissions.get_feature_toggle_state"
    ).return_value = True
    group = create_autospec(Group, id=1234)
    group.name = "app-sre"
    group.projects = create_autospec(GroupProjectManager)
    group.shared_projects = create_autospec(SharedProjectManager)
    mocked_gl.get_group.return_value = group
    mocked_gl.get_access_level.return_value = 40
    project = None
    mocked_gl.get_project.return_value = project
    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.share_project_with_group.assert_not_called()


def test_run_reshare_with_group(
    mocked_queries: MagicMock, mocker: MockerFixture, mocked_gl: MagicMock
) -> None:
    mocker.patch("reconcile.gitlab_permissions.GitLabApi").return_value = mocked_gl
    mocker.patch(
        "reconcile.gitlab_permissions.get_feature_toggle_state"
    ).return_value = True
    group = create_autospec(Group, id=1234)
    group.name = "app-sre"
    group.projects = create_autospec(GroupProjectManager)
    group.shared_projects = create_autospec(SharedProjectManager)
    shared_project = create_autospec(
        SharedProject,
        web_url=GITLAB_TEST_URL,
        shared_with_groups=[
            {
                "group_access_level": 30,
                "group_name": "app-sre",
                "group_id": 1234,
            }
        ],
    )
    group.shared_projects.list.return_value = [shared_project]
    mocked_gl.get_group.return_value = group
    mocked_gl.get_access_level.return_value = 40
    project = create_autospec(Project, web_url=GITLAB_TEST_URL)
    project.members_all = create_autospec(ProjectMemberAllManager)
    project.members_all.get.return_value = create_autospec(
        ProjectMember, id=mocked_gl.user.id, access_level=40
    )
    mocked_gl.get_project.return_value = project
    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.share_project_with_group.assert_called_once_with(
        project=project, group_id=1234, access_level=40, reshare=True
    )


def test_run_share_with_group_failed(
    mocked_queries: MagicMock, mocker: MockerFixture, mocked_gl: MagicMock
) -> None:
    mocker.patch("reconcile.gitlab_permissions.GitLabApi").return_value = mocked_gl
    mocker.patch(
        "reconcile.gitlab_permissions.get_feature_toggle_state"
    ).return_value = True
    group = create_autospec(Group, id=1234)
    group.name = "app-sre"
    group.projects = create_autospec(GroupProjectManager)
    group.shared_projects = create_autospec(SharedProjectManager)
    group.projects = create_autospec(GroupProjectManager)
    group.shared_projects = create_autospec(SharedProjectManager)
    shared_project = create_autospec(
        SharedProject,
        web_url="https://test-gitlab.com",
        shared_with_groups=[
            {
                "group_access_level": 30,
                "group_name": "app-sre",
                "group_id": 134,
            }
        ],
    )
    group.shared_projects.list.return_value = [shared_project]
    mocked_gl.get_group.return_value = group
    mocked_gl.get_access_level.return_value = 40
    project = create_autospec(Project)
    project.members_all = create_autospec(ProjectMemberAllManager)
    project.members_all.get.return_value = create_autospec(
        ProjectMember, id=mocked_gl.user.id, access_level=10
    )
    mocked_gl.get_project.return_value = project
    with pytest.raises(Exception):
        gitlab_permissions.run(False, thread_pool_size=1)
