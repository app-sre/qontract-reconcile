from reconcile.utils import repo_owners


def test_repo_owners_subpath() -> None:
    def _mock_get_owners_map():
        return {
            "/foo": {
                "approvers": ["foo_approver"],
                "reviewers": ["foo_reviewer"],
            },
            "/foobar": {
                "approvers": ["foobar_approver"],
                "reviewers": ["foobar_reviewer"],
            },
            "/bar": {
                "approvers": ["bar_approver"],
                "reviewers": ["bar_reviewer"],
            },
        }

    owners = repo_owners.RepoOwners(None)
    owners._get_owners_map = _mock_get_owners_map  # type: ignore
    assert owners.get_path_owners("/foobar/baz") == {
        "approvers": ["foobar_approver"],
        "reviewers": ["foobar_reviewer"],
    }


def test_repo_owners_subpath_closest() -> None:
    def _mock_get_owners_map():
        return {
            "/": {
                "approvers": ["root_approver"],
                "reviewers": ["root_reviewer"],
            },
            "/foo": {
                "approvers": ["foo_approver"],
                "reviewers": ["foo_reviewer"],
            },
        }

    owners = repo_owners.RepoOwners(None)
    owners._get_owners_map = _mock_get_owners_map  # type: ignore
    assert owners.get_path_closest_owners("/foobar/baz") == {
        "approvers": ["root_approver"],
        "reviewers": ["root_reviewer"],
    }
