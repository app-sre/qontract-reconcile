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
    def org_invitations(org_name):
        return []

    @staticmethod
    def team_invitations(org_id, team_id):
        return []


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__dict__ = self


class GithubMock:
    def __init__(self, spec):
        self.spec = spec

    class GithubOrgMock:
        def __init__(self, spec_org):
            self.spec_org = spec_org

        @property
        def id(self):
            return self.spec_org["id"]

        class GithubTeamMock:
            def __init__(self, spec_team):
                self.spec_team = spec_team

            def get_members(self):
                return map(AttrDict, self.spec_team["members"])

            @property
            def id(self):
                return self.spec_team["name"]

            @property
            def name(self):
                return self.spec_team["name"]

        def get_members(self):
            return map(AttrDict, self.spec_org["members"])

        def get_teams(self):
            return map(self.GithubTeamMock, self.spec_org["teams"])

    def get_organization(self, org_name):
        return self.GithubOrgMock(self.spec[org_name])


def get_items_by_params(state, params):
    h = AggregatedList.hash_params(params)
    for group in state:
        this_h = AggregatedList.hash_params(group["params"])

        if h == this_h:
            return sorted(group["items"])
    return False


class TestGithubOrg:
    @staticmethod
    def setup_method(method):
        config.init_from_toml(fxt.path("config.toml"))
        gql.init_from_config(autodetect_sha=False)

    @staticmethod
    def do_current_state_test(path):
        fixture = fxt.get_anymarkup(path)

        with patch("reconcile.github_org.RawGithubApi") as m_rga:
            with patch("reconcile.github_org.Github") as m_gh:
                m_gh.return_value = GithubMock(fixture["gh_api"])
                m_rga.return_value = RawGithubApiMock()

                gh_api_store = github_org.GHApiStore(config.get_config())
                current_state = github_org.fetch_current_state(gh_api_store)
                current_state = current_state.dump()

                expected_current_state = fixture["state"]

                assert len(current_state) == len(expected_current_state)
                for group in current_state:
                    params = group["params"]
                    items = sorted(group["items"])
                    assert items == get_items_by_params(expected_current_state, params)

    @staticmethod
    def do_desired_state_test(path):
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

    def test_current_state_simple(self):
        self.do_current_state_test("current_state_simple.yml")

    def test_desired_state_simple(self):
        self.do_desired_state_test("desired_state_simple.yml")

    def test_get_members(self):
        class SimpleMemberMock:
            def __init__(self, login):
                self.login = login

        class SimpleOrgMock:
            @staticmethod
            def get_members():
                return [SimpleMemberMock("a"), SimpleMemberMock("b")]

        org = SimpleOrgMock()
        assert github_org.get_members(org) == ["a", "b"]

    def test_get_org_teams(self):
        class SimpleOrgMock:
            @staticmethod
            def get_teams():
                return ["teams"]

        class SimpleGithubMock:
            @staticmethod
            def get_organization(org_name):
                return SimpleOrgMock()

        g = SimpleGithubMock()
        _, teams = github_org.get_org_and_teams(g, "org")
        assert teams == ["teams"]
