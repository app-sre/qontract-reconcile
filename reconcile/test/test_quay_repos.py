from mock import patch

import reconcile.utils.config as config
import reconcile.utils.gql as gql
import reconcile.quay_repos as quay_repos

from reconcile.utils.aggregated_list import AggregatedList

from .fixtures import Fixtures


fxt = Fixtures('quay_repos')


def get_items_by_params(state, params):
    h = AggregatedList.hash_params(params)
    for group in state:
        this_h = AggregatedList.hash_params(group['params'])

        if h == this_h:
            return sorted(group['items'])
    return False


class QuayApiMock:
    def __init__(self, list_images_response):
        self.list_images_response = list_images_response

    def list_images(self):
        return self.list_images_response


class TestQuayRepos:
    @staticmethod
    def setup_method(method):
        config.init_from_toml(fxt.path('config.toml'))
        gql.init_from_config(sha_url=False)

    @staticmethod
    def do_current_state_test(path):
        fixture = fxt.get_anymarkup(path)

        quay_org_catalog = fixture['quay_org_catalog']

        store = {}
        for org_data in quay_org_catalog:
            name = org_data['name']
            store[name] = {'api': QuayApiMock(org_data['repos']),
                           'managedRepos': org_data['managedRepos']}

        current_state = quay_repos.fetch_current_state(store)
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

    @staticmethod
    def do_desired_state_test(path):
        fixture = fxt.get_anymarkup(path)

        with patch('reconcile.utils.gql.GqlApi.query') as m_gql:
            m_gql.return_value = fixture['gql_response']

            desired_state = quay_repos.fetch_desired_state().dump()

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
