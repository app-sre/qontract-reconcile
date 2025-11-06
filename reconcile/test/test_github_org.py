from collections.abc import Iterable, Mapping
from typing import Any
from unittest.mock import patch

from reconcile import github_org
from reconcile.utils import (
    config,
    gql,
)
from reconcile.utils.aggregated_list import AggregatedList

from .fixtures import Fixtures

fxt = Fixtures("github_org")


class RawGithubApiMock:
    @staticmethod
    def org_invitations(org_name: str) -> list:
        return []

    @staticmethod
    def team_invitations(org_id: str, team_id: str) -> list:
        return []


class AttrDict(dict):  # noqa: FURB189
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.__dict__ = self


class GithubMock:
    def __init__(self, spec: dict) -> None:
        self.spec = spec

    class GithubOrgMock:
        def __init__(self, spec_org: dict) -> None:
            self.spec_org = spec_org

        @property
        def id(self) -> str:
            return self.spec_org["id"]

        class GithubTeamMock:
            def __init__(self, spec_team: dict) -> None:
                self.spec_team = spec_team

            def get_members(self) -> Iterable[dict]:
                return map(AttrDict, self.spec_team["members"])

            @property
            def id(self) -> str:
                return self.spec_team["name"]

            @property
            def name(self) -> str:
                return self.spec_team["name"]

        def get_members(self) -> Iterable[dict]:
            return map(AttrDict, self.spec_org["members"])

        def get_teams(self) -> Iterable[GithubTeamMock]:
            return map(self.GithubTeamMock, self.spec_org["teams"])

    def get_organization(self, org_name: str) -> GithubOrgMock:
        return self.GithubOrgMock(self.spec[org_name])


def get_items_by_params(state: Iterable[Mapping], params: Mapping) -> list | bool:
    h = AggregatedList.hash_params(params)
    for group in state:
        this_h = AggregatedList.hash_params(group["params"])

        if h == this_h:
            return sorted(group["items"])
    return False


class TestGithubOrg:
    @staticmethod
    def setup_method(method: Any) -> None:
        config.init_from_toml(fxt.path("config.toml"))
        gql.init_from_config(autodetect_sha=False)

    @staticmethod
    def do_current_state_test(path: str) -> None:
        fixture = fxt.get_anymarkup(path)

        with (
            patch("reconcile.github_org.RawGithubApi") as m_rga,
            patch("reconcile.github_org.Github") as m_gh,
        ):
            m_gh.return_value = GithubMock(fixture["gh_api"])
            m_rga.return_value = RawGithubApiMock()

            gh_api_store = github_org.GHApiStore(config.get_config())
            current_state = github_org.fetch_current_state(gh_api_store).dump()

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

            desired_state = github_org.fetch_desired_state(infer_clusters=False).dump()

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

    def test_get_members(self) -> None:
        class SimpleMemberMock:  # noqa: B903
            def __init__(self, login: str) -> None:
                self.login = login

        class SimpleOrgMock:
            @staticmethod
            def get_members() -> list[SimpleMemberMock]:
                return [SimpleMemberMock("a"), SimpleMemberMock("b")]

        org = SimpleOrgMock()
        assert github_org.get_members(org) == ["a", "b"]  # type: ignore[arg-type]

    def test_get_org_teams(self) -> None:
        class SimpleOrgMock:
            @staticmethod
            def get_teams() -> list[str]:
                return ["teams"]

        class SimpleGithubMock:
            @staticmethod
            def get_organization(org_name: str) -> SimpleOrgMock:
                return SimpleOrgMock()

        g = SimpleGithubMock()
        _, teams = github_org.get_org_and_teams(g, "org")  # type: ignore[arg-type]
        assert teams == ["teams"]
