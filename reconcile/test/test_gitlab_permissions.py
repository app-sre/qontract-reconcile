from unittest.mock import MagicMock, create_autospec

import pytest
from gitlab.v4.objects import CurrentUser, GroupMember
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
        {"https://test.com": {"group_access_level": 30}},
    )
    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.share_project_with_group.assert_called_once_with(
        repo_url="https://test-gitlab.com", group_id=1234, dry_run=False
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
        {"https://test-gitlab.com": {"group_access_level": 30}},
    )
    gitlab_permissions.run(False, thread_pool_size=1)
    mocked_gl.share_project_with_group.assert_called_once_with(
        repo_url="https://test-gitlab.com", group_id=1234, dry_run=False, reshare=True
    )
