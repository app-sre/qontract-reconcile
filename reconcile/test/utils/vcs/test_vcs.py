from collections.abc import Callable, Mapping
from datetime import datetime
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest, ProjectMergeRequestPipeline

from reconcile.utils.vcs import VCS, Commit, MRCheckStatus, VCSMissingSourceBranchError


# https://docs.gitlab.com/ee/api/pipelines.html
@pytest.mark.parametrize(
    "pipelines, expected_status",
    [
        ([{"status": "success"}], MRCheckStatus.SUCCESS),
        ([{"status": "failed"}], MRCheckStatus.FAILED),
        ([{"status": "canceled"}], MRCheckStatus.NONE),
        ([], MRCheckStatus.NONE),
    ],
)
def test_gitlab_mr_check_status(
    vcs_builder: Callable[[Mapping], VCS],
    pipelines: list[Mapping],
    expected_status: MRCheckStatus,
) -> None:
    vcs = vcs_builder({
        "MR_PIPELINES": [
            create_autospec(ProjectMergeRequestPipeline, **p) for p in pipelines
        ],
    })

    mr = create_autospec(spec=ProjectMergeRequest)
    assert vcs.get_gitlab_mr_check_status(mr=mr) == expected_status


def test_commits_between_gitlab(vcs_builder: Callable[[Mapping], VCS]) -> None:
    vcs = vcs_builder({
        "REPO": "https://gitlab.com/some/repo",
        "COMMITS": ["sha1", "sha2"],
    })

    commits = vcs.get_commits_between(
        repo_url="https://gitlab.com/some/repo",
        commit_from="from",
        commit_to="to",
        auth_code=None,
    )

    assert sorted(commits) == sorted([
        Commit(
            repo="https://gitlab.com/some/repo",
            sha="sha1",
            date=datetime.fromisoformat("2021-01-01T00:00:00Z"),
        ),
        Commit(
            repo="https://gitlab.com/some/repo",
            sha="sha2",
            date=datetime.fromisoformat("2021-01-01T00:00:00Z"),
        ),
    ])

    vcs._gitlab_instance.repository_compare.assert_called_once_with(  # type: ignore[attr-defined]
        ref_from="from", ref_to="to", repo_url="https://gitlab.com/some/repo"
    )
    vcs._gh_per_repo_url["https://gitlab.com/some/repo"].compare.assert_not_called()  # type: ignore[attr-defined]


def test_commits_between_github(vcs_builder: Callable[[Mapping], VCS]) -> None:
    vcs = vcs_builder({
        "REPO": "https://github.com/some/repo",
        "COMMITS": ["sha1", "sha2"],
    })
    commits = vcs.get_commits_between(
        repo_url="https://github.com/some/repo",
        commit_from="from",
        commit_to="to",
        auth_code=None,
    )
    vcs._gh_per_repo_url[
        "https://github.com/some/repo"
    ].compare.assert_called_once_with(commit_from="from", commit_to="to")  # type: ignore[attr-defined]
    assert sorted(commits) == sorted([
        Commit(
            repo="https://github.com/some/repo",
            sha="sha1",
            date=datetime.fromisoformat("2021-01-01T00:00:00Z"),
        ),
        Commit(
            repo="https://github.com/some/repo",
            sha="sha2",
            date=datetime.fromisoformat("2021-01-01T00:00:00Z"),
        ),
    ])
    vcs._gitlab_instance.repository_compare.assert_not_called()  # type: ignore[attr-defined]


def test_close_mr_success(vcs_builder: Callable[[Mapping], VCS]) -> None:
    vcs = vcs_builder({})
    mr = create_autospec(spec=ProjectMergeRequest)
    mr.attributes = {"source_branch": "test"}
    vcs.close_app_interface_mr(mr=mr, comment="test")
    vcs._app_interface_api.close.assert_called_once_with(mr)  # type: ignore[attr-defined]
    vcs._app_interface_api.delete_branch.assert_called_once_with("test")  # type: ignore[attr-defined]


def test_close_mr_error(vcs_builder: Callable[[Mapping], VCS]) -> None:
    vcs = vcs_builder({})
    mr = create_autospec(spec=ProjectMergeRequest)
    mr.attributes = {}
    with pytest.raises(VCSMissingSourceBranchError):
        vcs.close_app_interface_mr(mr=mr, comment="test")
    vcs._app_interface_api.close.assert_not_called()  # type: ignore[attr-defined]
    vcs._app_interface_api.delete_branch.assert_not_called()  # type: ignore[attr-defined]


def test_get_file_content_from_app_interface_ref_defaults(
    vcs_builder: Callable[[Mapping], VCS],
) -> None:
    vcs = vcs_builder({})
    vcs.get_file_content_from_app_interface_ref(file_path="/file.yaml")

    vcs._app_interface_api.get_raw_file.assert_called_once_with(  # type: ignore[attr-defined]
        project=vcs._app_interface_api.project,
        path="data/file.yaml",
        ref="master",
    )


def test_get_file_content_from_app_interface_ref_overrides(
    vcs_builder: Callable[[Mapping], VCS],
) -> None:
    vcs = vcs_builder({})
    vcs.get_file_content_from_app_interface_ref(
        file_path="/file.yaml", is_data=False, ref="ref"
    )

    vcs._app_interface_api.get_raw_file.assert_called_once_with(  # type: ignore[attr-defined]
        project=vcs._app_interface_api.project,
        path="/file.yaml",
        ref="ref",
    )


@pytest.mark.parametrize(
    ["repo_url", "expected_platform", "expected_name"],
    [
        ("https://github.com/foo/bar", "github", "foo/bar"),
        ("https://github.com/foo/bar.git", "github", "foo/bar"),
        ("https://github.com/foo/bar/", "github", "foo/bar"),
        ("http://github.com/foo/bar", "github", "foo/bar"),
        ("https://github.ee.com/foo/bar", "github", "foo/bar"),
        ("https://gitlab.com/foo/bar", "gitlab", "foo/bar"),
        ("https://gitlab.com/foo/bar.git", "gitlab", "foo/bar"),
        ("https://gitlab.com/foo/bar/", "gitlab", "foo/bar"),
        ("http://gitlab.com/foo/bar", "gitlab", "foo/bar"),
        ("https://gitlab.ee.com/foo/bar", "gitlab", "foo/bar"),
        ("https://some-other-platform.com/foo/bar", None, "foo/bar"),
    ],
)
def test_parse_repo_url(
    repo_url: str,
    expected_platform: str | None,
    expected_name: str,
) -> None:
    repo_info = VCS.parse_repo_url(repo_url)

    assert repo_info.platform == expected_platform
    assert repo_info.name == expected_name
