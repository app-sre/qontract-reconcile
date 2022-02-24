from unittest.mock import patch

from reconcile.quay_repos import RepoInfo, act
from reconcile.quay_base import OrgKey

from .fixtures import Fixtures


fxt = Fixtures("quay_repos")


def build_state(fixture_state):
    return [
        RepoInfo(
            org_key=OrgKey("instance", "org"),
            name=item[0],
            public=item[1],
            description=item[2],
        )
        for item in fixture_state
    ]


def get_test_repo_from_state(state, name):
    for item in state:
        if item.name == name:
            return item
    return None


class TestQuayRepos:
    @staticmethod
    @patch("reconcile.quay_repos.act_public")
    @patch("reconcile.quay_repos.act_description")
    @patch("reconcile.quay_repos.act_delete")
    @patch("reconcile.quay_repos.act_create")
    def test_act(act_create, act_delete, act_description, act_public):
        fixture = fxt.get_anymarkup("state.yml")

        current_state = build_state(fixture["current_state"])
        desired_state = build_state(fixture["desired_state"])

        quay_api_store = {}
        dry_run = True
        act(dry_run, quay_api_store, current_state, desired_state)

        repo_delete = get_test_repo_from_state(current_state, "repo_delete")
        act_delete.assert_called_once_with(dry_run, quay_api_store, repo_delete)

        repo_create = get_test_repo_from_state(desired_state, "repo_create")
        act_create.assert_called_once_with(dry_run, quay_api_store, repo_create)

        repo_desc = get_test_repo_from_state(desired_state, "repo_desc")
        act_description.assert_called_once_with(dry_run, quay_api_store, repo_desc)

        repo_public = get_test_repo_from_state(desired_state, "repo_public")
        act_public.assert_called_once_with(dry_run, quay_api_store, repo_public)
