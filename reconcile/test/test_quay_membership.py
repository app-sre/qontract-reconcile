from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from unittest.mock import (
    MagicMock,
    patch,
)

from reconcile import quay_membership
from reconcile.quay_base import OrgKey
from reconcile.utils import (
    config,
    gql,
)
from reconcile.utils.aggregated_list import AggregatedList
from reconcile.utils.quay_api import QuayApi

from .fixtures import Fixtures

if TYPE_CHECKING:
    from reconcile.quay_base import QuayApiStore

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

        store: QuayApiStore = {}
        mock_apis: dict[OrgKey, QuayApiMock] = {}

        for org_data in quay_org_catalog:
            name_str = org_data["name"]
            name = OrgKey(instance="quay.io", org_name=name_str)

            mock_api = QuayApiMock(quay_org_teams.get(name_str, {}))
            mock_apis[name] = mock_api

            # Store org metadata (no api field)
            store[name] = {
                "teams": org_data["managedTeams"],
                "url": "",
                "push_token": None,
                "managedRepos": False,
                "mirror": None,
                "mirror_filters": {},
                "token": "test-token",
                "org_name": name.org_name,
                "base_url": "mock.quay.io",
            }

        def mock_get_quay_api_for_org(
            org_key: OrgKey, org_info: dict[str, Any]
        ) -> QuayApiMock:
            if org_key not in mock_apis:
                raise KeyError(
                    f"OrgKey {org_key} not found in mock_apis. Available keys: {list(mock_apis.keys())}"
                )
            return mock_apis[org_key]

        # Patch both the function and requests.Session to prevent any real HTTP connections
        # Also patch QuayApi.__init__ as a safety net to prevent real instances
        def mock_quay_api_init(
            token: str,
            organization: str,
            base_url: str = "quay.io",
            timeout: int = 60,
        ) -> None:
            # This should never be called if our patch works, but if it is, raise an error
            raise AssertionError(
                f"Real QuayApi.__init__ was called! This means get_quay_api_for_org patch failed. "
                f"token={token}, organization={organization}, base_url={base_url}"
            )

        with (
            patch(
                "reconcile.quay_membership.get_quay_api_for_org",
                side_effect=mock_get_quay_api_for_org,
            ),
            patch(
                "reconcile.utils.rest_api_base.requests.Session",
                return_value=MagicMock(),
            ),
            patch(
                "requests.Session",
                return_value=MagicMock(),
            ),
            patch.object(
                QuayApi,
                "__init__",
                mock_quay_api_init,
            ),
        ):
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
