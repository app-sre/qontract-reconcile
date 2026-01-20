from collections.abc import Callable
from typing import Any
from unittest.mock import (
    MagicMock,
    patch,
)

from reconcile import quay_membership
from reconcile.quay_base import OrgInfo, OrgKey, QuayApiStore
from reconcile.utils import (
    config,
    gql,
)
from reconcile.utils.aggregated_list import AggregatedList
from reconcile.utils.quay_api import QuayApi

from .fixtures import Fixtures

fxt = Fixtures("quay_membership")


def get_items_by_params(
    state: list[dict[str, Any]], params: dict[str, str]
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

    def __enter__(self) -> "QuayApiMock":
        # Context manager support
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
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


class TestQuayMembership:
    @staticmethod
    def setup_method(method: Callable) -> None:
        config.init_from_toml(fxt.path("config.toml"))
        gql.init_from_config(autodetect_sha=False)

    @staticmethod
    def do_current_state_test(path: str) -> None:
        fixture = fxt.get_anymarkup(path)

        quay_org_catalog = fixture["quay_org_catalog"]
        quay_org_teams = fixture["quay_org_teams"]

        # Patch get_quay_api_store to return empty dict, then create QuayApiStore
        # This prevents GraphQL queries during initialization
        with patch("reconcile.quay_base.get_quay_api_store", return_value={}):
            store = QuayApiStore()

            # Populate store with test data
            for org_data in quay_org_catalog:
                name_str = org_data["name"]
                name = OrgKey(instance="quay.io", org_name=name_str)

                # Create mock API instance
                mock_api = QuayApiMock(quay_org_teams.get(name_str, {}))

                # Store org metadata with api field (matching OrgInfo structure)
                store[name] = OrgInfo(
                    url="",
                    teams=org_data["managedTeams"],
                    push_token=None,
                    managedRepos=False,
                    mirror=None,
                    mirror_filters={},
                    api=mock_api,
                )

            # Use the store in a context manager to ensure cleanup
            with store:
                current_state = quay_membership.fetch_current_state(store).dump()

        expected_current_state = fixture["state"]

        assert len(current_state) == len(expected_current_state)
        for group in current_state:
            params = group["params"]
            items = sorted(group["items"])
            assert items == get_items_by_params(expected_current_state, params)

    @staticmethod
    def do_desired_state_test(path: str) -> None:
        fixture = fxt.get_anymarkup(path)

        with patch("reconcile.utils.gql.GqlApi.query") as m_gql:
            m_gql.return_value = fixture["gql_response"]

            desired_state = quay_membership.fetch_desired_state().dump()

            expected_desired_state = fixture["state"]

            assert len(desired_state) == len(expected_desired_state)
            for group in desired_state:
                params = group["params"]
                items = sorted(group["items"])
                assert items == get_items_by_params(expected_desired_state, params)

    def test_current_state_simple(self) -> None:
        self.do_current_state_test("current_state_simple.yml")

    def test_desired_state_simple(self) -> None:
        self.do_desired_state_test("desired_state_simple.yml")
