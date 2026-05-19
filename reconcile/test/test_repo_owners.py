from unittest.mock import create_autospec

import pytest

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


def test_get_owners_map_parses_yaml() -> None:
    cli = create_autospec(GitLabApi)
    cli.get_repository_tree.return_value = [{"name": "OWNERS", "path": "OWNERS"}]
    cli.get_file.side_effect = lambda path, ref: {
        "OWNERS": "approvers:\n- user1\nreviewers:\n- user2\n",
        "OWNERS_ALIASES": None,
    }[path]

    owners = RepoOwners(cli, ref="main")
    result = owners.owners_map

    assert "." in result
    assert result["."]["approvers"] == {"user1"}
    assert result["."]["reviewers"] == {"user2"}


def test_get_owners_map_handles_invalid_yaml() -> None:
    cli = create_autospec(GitLabApi)
    cli.get_repository_tree.return_value = [{"name": "OWNERS", "path": "OWNERS"}]
    cli.get_file.side_effect = lambda path, ref: {
        "OWNERS": ":\n  - :\n  invalid: [",
        "OWNERS_ALIASES": None,
    }[path]

    owners = RepoOwners(cli, ref="main")
    result = owners.owners_map
    assert result == {}


def test_get_owners_map_resolves_aliases() -> None:
    cli = create_autospec(GitLabApi)
    cli.get_repository_tree.return_value = [{"name": "OWNERS", "path": "OWNERS"}]
    cli.get_file.side_effect = lambda path, ref: {
        "OWNERS": "approvers:\n- team-a\nreviewers: []\n",
        "OWNERS_ALIASES": "aliases:\n  team-a:\n  - alice\n  - bob\n",
    }[path]

    owners = RepoOwners(cli, ref="main")
    result = owners.owners_map

    assert result["."]["approvers"] == {"alice", "bob"}


@pytest.mark.parametrize(
    "raw_content",
    [
        None,
        "null",
        "not-a-dict",
        "42",
    ],
)
def test_get_owners_map_skips_invalid_content(raw_content: str | None) -> None:
    cli = create_autospec(GitLabApi)
    cli.get_repository_tree.return_value = [{"name": "OWNERS", "path": "OWNERS"}]
    cli.get_file.side_effect = lambda path, ref: {
        "OWNERS": raw_content,
        "OWNERS_ALIASES": None,
    }[path]

    owners = RepoOwners(cli, ref="main")
    result = owners.owners_map
    assert result == {}
