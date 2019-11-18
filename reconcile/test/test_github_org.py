from mock import patch
from .fixtures import Fixtures

import utils.config as config
import utils.gql as gql
import reconcile.github_org as github_org
from utils.aggregated_list import AggregatedList

fxt = Fixtures('github_org')


class RawGithubApiMock(object):
    def org_invitations(self, org_name):
        return []

    def team_invitations(self, team_id):
        return []


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


class GithubMock(object):
    def __init__(self, spec):
        self.spec = spec

    class GithubOrgMock(object):
        def __init__(self, spec_org):
            self.spec_org = spec_org

        class GithubTeamMock(object):
            def __init__(self, spec_team):
                self.spec_team = spec_team

            def get_members(self):
                return map(lambda e: AttrDict(e), self.spec_team["members"])

            @property
            def id(self):
                return self.spec_team["name"]

            @property
            def name(self):
                return self.spec_team["name"]

        def get_members(self):
            return map(lambda e: AttrDict(e), self.spec_org["members"])

        def get_teams(self):
            return map(
                lambda e: self.GithubTeamMock(e),
                self.spec_org["teams"]
            )

    def get_organization(self, org_name):
        return self.GithubOrgMock(self.spec[org_name])


def get_items_by_params(state, params):
    h = AggregatedList.hash_params(params)
    for group in state:
        this_h = AggregatedList.hash_params(group['params'])

        if h == this_h:
            return sorted(group['items'])
    return False


class TestGithubOrg(object):
    def setup_method(self, method):
        config.init_from_toml(fxt.path('config.toml'))
        gql.init_from_config(sha_url=False)

    def do_current_state_test(self, path):
        fixture = fxt.get_anymarkup(path)

        with patch('reconcile.github_org.RawGithubApi') as m_rga:
            with patch('reconcile.github_org.Github') as m_gh:
                m_gh.return_value = GithubMock(fixture['gh_api'])
                m_rga.return_value = RawGithubApiMock()

                gh_api_store = github_org.GHApiStore(config.get_config())
                current_state = github_org.fetch_current_state(gh_api_store)
                current_state = current_state.dump()

                expected_current_state = fixture['state']

                assert len(current_state) == len(expected_current_state)
                for group in current_state:
                    params = group['params']
                    items = sorted(group['items'])
                    assert items == get_items_by_params(
                        expected_current_state,
                        params
                    )

    def do_desired_state_test(self, path):
        fixture = fxt.get_anymarkup(path)

        with patch('utils.gql.GqlApi.query') as m_gql:
            m_gql.return_value = fixture['gql_response']

            desired_state = github_org.fetch_desired_state(
                infer_clusters=False).dump()

            expected_desired_state = fixture['state']

            assert len(desired_state) == len(expected_desired_state)
            for group in desired_state:
                params = group['params']
                items = sorted(group['items'])
                assert items == get_items_by_params(
                    expected_desired_state,
                    params
                )

    def test_current_state_simple(self):
        self.do_current_state_test('current_state_simple.yml')

    def test_desired_state_simple(self):
        self.do_desired_state_test('desired_state_simple.yml')
