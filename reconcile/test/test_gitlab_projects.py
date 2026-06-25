import logging
from unittest.mock import Mock, create_autospec

import pytest
from gitlab.const import DEVELOPER_ACCESS
from gitlab.v4.objects import Project
from pytest_mock import MockerFixture

from reconcile import gitlab_projects
from reconcile.utils.gitlab_api import GitLabApi

PROJECT_URL = "http://gitlab.example.com/service/my-project"
ARGO_PLATFORM_ADMIN_SHARE = [
    {"group": "argo-platform-admin", "accessLevel": "developer"},
]


@pytest.fixture
def project_url() -> str:
    return PROJECT_URL


@pytest.fixture
def argo_platform_admin_share() -> list[dict[str, str]]:
    return list(ARGO_PLATFORM_ADMIN_SHARE)


@pytest.fixture
def mocked_gitlab_api() -> Mock:
    gl = create_autospec(GitLabApi)
    gl.get_access_level.return_value = DEVELOPER_ACCESS
    gl.get_access_level_string.return_value = "developer"
    return gl


@pytest.fixture
def mocked_project() -> Mock:
    project = create_autospec(Project)
    project.shared_with_groups = []
    return project


@pytest.fixture
def mocked_project_with_argo_share() -> Mock:
    project = create_autospec(Project)
    project.shared_with_groups = [
        {
            "group_name": "argo-platform-admin",
            "group_full_path": "argo-platform-admin",
            "group_access_level": DEVELOPER_ACCESS,
        },
    ]
    return project


def test_reconcile_project_shared_groups_add(
    mocked_gitlab_api: Mock,
    mocked_project: Mock,
    project_url: str,
    argo_platform_admin_share: list[dict[str, str]],
) -> None:
    mocked_gitlab_api.get_project.return_value = mocked_project

    gitlab_projects.reconcile_project_shared_groups(
        gl=mocked_gitlab_api,
        project_url=project_url,
        shared_with_groups=argo_platform_admin_share,
        dry_run=False,
    )

    mocked_gitlab_api.get_access_level.assert_called_once_with("developer")
    mocked_gitlab_api.share_project_with_group.assert_called_once_with(
        mocked_project, "argo-platform-admin", "developer"
    )


def test_reconcile_project_shared_groups_dry_run_missing_project(
    mocked_gitlab_api: Mock,
    project_url: str,
    argo_platform_admin_share: list[dict[str, str]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocked_gitlab_api.get_project.return_value = None

    with caplog.at_level(logging.INFO):
        gitlab_projects.reconcile_project_shared_groups(
            gl=mocked_gitlab_api,
            project_url=project_url,
            shared_with_groups=argo_platform_admin_share,
            dry_run=True,
        )

    mocked_gitlab_api.share_project_with_group.assert_not_called()
    assert "share_project_with_group" in caplog.text


def test_run_skips_null_shared_with_groups(mocker: MockerFixture) -> None:
    gl = create_autospec(GitLabApi)
    gl.get_group_id_and_projects.return_value = ("1", {"existing-project"})
    mocker.patch(
        "reconcile.gitlab_projects.queries.get_gitlab_instance",
        return_value={
            "projectRequests": [
                {
                    "group": "service",
                    "projects": ["existing-project"],
                    "sharedWithGroups": None,
                },
            ],
        },
    )
    mocker.patch(
        "reconcile.gitlab_projects.queries.get_app_interface_settings", return_value={}
    )
    mocker.patch(
        "reconcile.gitlab_projects.queries.get_code_components", return_value=[]
    )
    mocker.patch("reconcile.gitlab_projects.GitLabApi", return_value=gl)
    reconcile_mock = mocker.patch(
        "reconcile.gitlab_projects.reconcile_project_shared_groups"
    )
    mocker.patch("reconcile.gitlab_projects.sys.exit")

    gitlab_projects.run(dry_run=True)

    reconcile_mock.assert_not_called()


def test_reconcile_project_shared_groups_unshare(
    mocked_gitlab_api: Mock,
    mocked_project_with_argo_share: Mock,
    project_url: str,
) -> None:
    mocked_gitlab_api.get_project.return_value = mocked_project_with_argo_share
    mocked_gitlab_api.get_project_shared_groups.return_value = {
        "argo-platform-admin": DEVELOPER_ACCESS,
    }

    gitlab_projects.reconcile_project_shared_groups(
        gl=mocked_gitlab_api,
        project_url=project_url,
        shared_with_groups=[],
        dry_run=False,
    )

    mocked_gitlab_api.unshare_project_from_group.assert_called_once_with(
        mocked_project_with_argo_share, "argo-platform-admin"
    )
