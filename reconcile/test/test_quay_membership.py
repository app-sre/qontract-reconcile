from __future__ import annotations

from typing import Any, Self
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from reconcile import quay_membership
from reconcile.quay_base import OrgInfo, OrgKey, QuayApiStore
from reconcile.utils import (
    config,
    gql,
)
from reconcile.utils.aggregated_list import AggregatedItem, AggregatedList
from reconcile.utils.quay_api import QuayApi

from .fixtures import Fixtures

fxt = Fixtures("quay_membership")


def get_items_by_params(
    state: list[AggregatedItem], params: dict[str, str]
) -> list[str] | bool:
    h = AggregatedList.hash_params(params)
    for group in state:
        this_h = AggregatedList.hash_params(group["params"])

        if h == this_h:
            return sorted(group["items"])
    return False


class QuayApiMock(QuayApi):
    def __init__(self, list_team_members_response: dict[str, list[dict]]):
        # Initialize ApiBase attributes manually with mocked session
        self.host = "https://mock.quay.io"
        self.max_retries = 3
        self.read_timeout = 60
        self.session = MagicMock()  # Mock session to prevent real HTTP requests

        # Initialize QuayApi-specific attributes
        self.organization = "mock-org"
        self.team_members: dict[str, Any] = {}
        self.list_team_members_response = list_team_members_response

    def __enter__(self) -> Self:
        # Context manager support
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        # Context manager cleanup - do nothing since we're using a mock session
        pass

    def list_team_members(self, team: str, **kwargs: Any) -> list[dict]:
        # Return mock response directly, bypassing any parent implementation
        return self.list_team_members_response.get(team, [])

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        # Override _get to prevent any accidental real HTTP requests
        # This should never be called since we override list_team_members
        raise AssertionError(
            f"QuayApiMock._get() should not be called. URL: {url}, params: {params}"
        )

    def cleanup(self) -> None:
        # Override cleanup to do nothing since we're using a mock session
        pass


@pytest.fixture(autouse=True)
def quay_membership_config() -> None:
    config.init_from_toml(fxt.path("config.toml"))
    gql.init_from_config(autodetect_sha=False)


def build_quay_api_store(fixture: dict[str, Any]) -> QuayApiStore:
    quay_org_catalog = fixture["quay_org_catalog"]
    quay_org_teams = fixture["quay_org_teams"]
    store = QuayApiStore()

    for org_data in quay_org_catalog:
        name_str = org_data["name"]
        name = OrgKey(instance="quay.io", org_name=name_str)
        mock_api = QuayApiMock(quay_org_teams.get(name_str, {}))
        store[name] = OrgInfo(
            url="",
            teams=org_data["managedTeams"],
            push_token=None,
            managedRepos=False,
            mirror=None,
            mirror_filters={},
            api=mock_api,
        )

    return store


def assert_state_matches(
    actual_state: list[AggregatedItem], expected_state: list[AggregatedItem]
) -> None:
    assert len(actual_state) == len(expected_state)
    for group in actual_state:
        params = group["params"]
        items = sorted(group["items"])
        assert items == get_items_by_params(expected_state, params)


def test_current_state_simple() -> None:
    fixture = fxt.get_anymarkup("current_state_simple.yml")
    store = build_quay_api_store(fixture)

    with store:
        current_state = quay_membership.fetch_current_state(store).dump()

    assert_state_matches(current_state, fixture["state"])


def test_desired_state_simple() -> None:
    fixture = fxt.get_anymarkup("desired_state_simple.yml")

    with patch("reconcile.utils.gql.GqlApi.query") as m_gql:
        m_gql.return_value = fixture["gql_response"]
        desired_state = quay_membership.fetch_desired_state().dump()

    assert_state_matches(desired_state, fixture["state"])
