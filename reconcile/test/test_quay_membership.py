from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from reconcile import quay_membership
from reconcile.utils import (
    config,
    gql,
)
from reconcile.utils.aggregated_list import AggregatedList
from reconcile.utils.quay_api import QuayApi

from .fixtures import Fixtures

if TYPE_CHECKING:
    from reconcile.quay_base import OrgKey, QuayApiStore

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
        self.list_team_members_response = list_team_members_response

    def list_team_members(self, team: str, **kwargs: Any) -> list[dict]:
        return self.list_team_members_response[team]


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
        for org_data in quay_org_catalog:
            name: OrgKey = org_data["name"]
            store[name] = {
                "api": QuayApiMock(quay_org_teams[name]),
                "teams": org_data["managedTeams"],
                "url": "",
                "push_token": None,
                "managedRepos": False,
                "mirror": None,
                "mirror_filters": {},
            }

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
