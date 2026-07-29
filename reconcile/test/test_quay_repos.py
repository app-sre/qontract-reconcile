from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import (
    MagicMock,
    Mock,
    patch,
)

import pytest

from reconcile.quay_base import OrgInfo, OrgKey, QuayApiStore
from reconcile.quay_repos import (
    RepoInfo,
    act,
)

from .fixtures import Fixtures

if TYPE_CHECKING:
    from collections.abc import Iterator

fxt = Fixtures("quay_repos")


def build_state(fixture_state: list[tuple[str, bool, str]]) -> list[RepoInfo]:
    return [
        RepoInfo(
            org_key=OrgKey("instance", "org"),
            name=item[0],
            public=item[1],
            description=item[2],
        )
        for item in fixture_state
    ]


def get_test_repo_from_state(state: list[RepoInfo], name: str) -> RepoInfo | None:
    for item in state:
        if item.name == name:
            return item
    return None


@pytest.fixture
def quay_api_store() -> Iterator[QuayApiStore]:
    org_key = OrgKey("instance", "org")
    mock_api = MagicMock()
    test_data: dict[OrgKey, OrgInfo] = {
        org_key: {
            "url": "",
            "push_token": None,
            "teams": [],
            "managedRepos": True,
            "mirror": None,
            "mirror_filters": {},
            "api": mock_api,
        }
    }
    store = QuayApiStore(test_data)
    with store:
        yield store


@patch("reconcile.quay_repos.act_public")
@patch("reconcile.quay_repos.act_description")
@patch("reconcile.quay_repos.act_delete")
@patch("reconcile.quay_repos.act_create")
def test_act(
    act_create: Mock,
    act_delete: Mock,
    act_description: Mock,
    act_public: Mock,
    quay_api_store: QuayApiStore,
) -> None:
    fixture = fxt.get_anymarkup("state.yml")

    current_state = build_state(fixture["current_state"])
    desired_state = build_state(fixture["desired_state"])

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
