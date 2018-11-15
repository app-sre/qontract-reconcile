from .fixtures import Fixtures
# import vcr

# import reconcile.github_org
import reconcile.config as config
import reconcile.gql as gql


class TestGithubOrg(object):
    ft = Fixtures('github_org')

    def setup_method(self, method):
        config.init_from_toml(self.ft.path('config.toml'))
        gql.init_from_config()

    # @vcr.use_cassette(ft.path('fetch_current_state'))
    # def test_fetch_current_state(self):
    #     state = reconcile.github_org.fetch_current_state()
    #     assert state.toJSON() == self.ft.get('fetch_current_state.expected')

    # @vcr.use_cassette(ft.path('fetch_desired_state'))
    # def test_fetch_desired_state(self):
    #     state = reconcile.github_org.fetch_desired_state()
    #     assert state.toJSON() == self.ft.get('fetch_desired_state.expected')
