from collections.abc import Callable, Mapping
from datetime import datetime
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

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
        "MR_PIPELINES": pipelines,
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
    vcs._gh_per_repo_url["https://gitlab.com/some/repo"].compare.assert_not_called()


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
    ].compare.assert_called_once_with(commit_from="from", commit_to="to")
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
    vcs._app_interface_api.close.assert_called_once_with(mr)
    vcs._app_interface_api.delete_branch.assert_called_once_with("test")


def test_close_mr_error(vcs_builder: Callable[[Mapping], VCS]) -> None:
    vcs = vcs_builder({})
    mr = create_autospec(spec=ProjectMergeRequest)
    mr.attributes = {}
    with pytest.raises(VCSMissingSourceBranchError):
        vcs.close_app_interface_mr(mr=mr, comment="test")
    vcs._app_interface_api.close.assert_not_called()
    vcs._app_interface_api.delete_branch.assert_not_called()
