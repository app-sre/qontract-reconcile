from mock import patch
from .fixtures import Fixtures

import utils.config as config
import utils.gql as gql
import reconcile.openshift_rolebinding as openshift_rolebinding
from utils.aggregated_list import AggregatedList

fxt = Fixtures('openshift_rolebinding')


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


def get_items_by_params(state, params):
    h = AggregatedList.hash_params(params)
    for group in state:
        this_h = AggregatedList.hash_params(group['params'])

        if h == this_h:
            return sorted(group['items'])
    return False


class TestOpenshiftRolebinding(object):
    def setup_method(self, method):
        config.init_from_toml(fxt.path('config.toml'))
        gql.init_from_config()

    def do_current_state_test(self, path):
        fixture = fxt.get_anymarkup(path)
        namespaces = fixture['namespaces']

        vault_read_func = 'reconcile.openshift_rolebinding.vault_client.read'
        with patch(vault_read_func) as vcr:
            vcr.return_value = 'token'
            cluster_store = openshift_rolebinding.ClusterStore(namespaces)

        grb_func = 'reconcile.openshift_rolebinding.Openshift.get_rolebindings'
        with patch(grb_func) as grb:
            grb.return_value = fixture['rolebindings']

            current_state = openshift_rolebinding.fetch_current_state(
                cluster_store)

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

        roles = fixture['gql_response']['roles']
        desired_state = openshift_rolebinding.fetch_desired_state(roles)
        desired_state = desired_state.dump()

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
