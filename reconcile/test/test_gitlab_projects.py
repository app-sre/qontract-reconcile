import logging
from unittest.mock import create_autospec

import pytest
from gitlab.const import DEVELOPER_ACCESS
from gitlab.v4.objects import Project
from pytest_mock import MockerFixture

from reconcile import gitlab_projects
from reconcile.utils.gitlab_api import GitLabApi


def test_reconcile_project_shared_groups_add(mocker: MockerFixture) -> None:
    gl = create_autospec(GitLabApi)
    project = create_autospec(Project)
    project.shared_with_groups = []
    gl.get_project.return_value = project
    gl.get_access_level.return_value = DEVELOPER_ACCESS
    gl.get_access_level_string.return_value = "developer"

    gitlab_projects.reconcile_project_shared_groups(
        gl=gl,
        project_url="http://gitlab.example.com/service/my-project",
        shared_with_groups=[
            {"group": "argo-platform-admin", "accessLevel": "developer"},
        ],
        dry_run=False,
    )

    gl.get_access_level.assert_called_once_with("developer")
    gl.share_project_with_group.assert_called_once_with(
        project, "argo-platform-admin", "developer"
    )


def test_reconcile_project_shared_groups_dry_run_missing_project(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    gl = create_autospec(GitLabApi)
    gl.get_project.return_value = None
    gl.get_access_level.return_value = DEVELOPER_ACCESS
    gl.get_access_level_string.return_value = "developer"

    with caplog.at_level(logging.INFO):
        gitlab_projects.reconcile_project_shared_groups(
            gl=gl,
            project_url="http://gitlab.example.com/service/my-project",
            shared_with_groups=[
                {"group": "argo-platform-admin", "accessLevel": "developer"},
            ],
            dry_run=True,
        )

    gl.share_project_with_group.assert_not_called()
    assert "share_project_with_group" in caplog.text


def test_reconcile_project_shared_groups_unshare(mocker: MockerFixture) -> None:
    gl = create_autospec(GitLabApi)
    project = create_autospec(Project)
    project.shared_with_groups = [
        {
            "group_name": "argo-platform-admin",
            "group_full_path": "argo-platform-admin",
            "group_access_level": DEVELOPER_ACCESS,
        },
    ]
    gl.get_project.return_value = project
    gl.get_project_shared_groups.return_value = {
        "argo-platform-admin": DEVELOPER_ACCESS,
    }

    gitlab_projects.reconcile_project_shared_groups(
        gl=gl,
        project_url="http://gitlab.example.com/service/my-project",
        shared_with_groups=[],
        dry_run=False,
    )

    gl.unshare_project_from_group.assert_called_once_with(
        project, "argo-platform-admin"
    )
