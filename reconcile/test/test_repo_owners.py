from unittest.mock import create_autospec

from reconcile.utils.github_api import GithubRepositoryApi
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.repo_owners import RepoOwners


class MockedRepoOwners(RepoOwners):
    def __init__(
        self,
        git_cli: GitLabApi | GithubRepositoryApi,
        ref: str = "master",
        recursive: bool = True,
        owners_map: dict[str, dict[str, set[str]]] | None = None,
    ) -> None:
        super().__init__(git_cli, ref, recursive)
        self._owners_map = owners_map


def test_repo_owners_subpath() -> None:
    owners = MockedRepoOwners(
        create_autospec(GitLabApi),
        owners_map={
            "/foo": {
                "approvers": {"foo_approver"},
                "reviewers": {"foo_reviewer"},
            },
            "/foobar": {
                "approvers": {"foobar_approver"},
                "reviewers": {"foobar_reviewer"},
            },
            "/bar": {
                "approvers": {"bar_approver"},
                "reviewers": {"bar_reviewer"},
            },
        },
    )
    assert owners.get_path_owners("/foobar/baz") == {
        "approvers": ["foobar_approver"],
        "reviewers": ["foobar_reviewer"],
    }


def test_repo_owners_subpath_closest() -> None:
    owners = MockedRepoOwners(
        create_autospec(GitLabApi),
        owners_map={
            "/": {
                "approvers": {"root_approver"},
                "reviewers": {"root_reviewer"},
            },
            "/foo": {
                "approvers": {"foo_approver"},
                "reviewers": {"foo_reviewer"},
            },
        },
    )
    assert owners.get_path_closest_owners("/foobar/baz") == {
        "approvers": ["root_approver"],
        "reviewers": ["root_reviewer"],
    }
