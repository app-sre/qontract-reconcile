import re
import logging

import e2e_tests.test_base as tb
import e2e_tests.network_policy_test_base as npt

from utils.defer import defer

QONTRACT_E2E_TEST = 'default-network-policies'


@defer
def run(defer=None):
    oc_map = tb.get_oc_map(QONTRACT_E2E_TEST)
    defer(lambda: oc_map.cleanup())
    pattern = tb.get_namespaces_pattern()
    for cluster in oc_map.clusters():
        oc = oc_map.get(cluster)
        logging.info("[{}] validating default NetworkPolicies".format(cluster))

        projects = [p['metadata']['name']
                    for p in oc.get_all('Project')['items']
                    if p['status']['phase'] != 'Terminating' and
                    not re.search(pattern, p['metadata']['name'])]

        all_network_policies = \
            oc.get_all('NetworkPolicy', all_namespaces=True)['items']
        network_policies = [np for np in all_network_policies
                            if np['metadata']['namespace'] in projects
                            and np['metadata']['name'] in
                            npt.get_expected_network_policy_names()]

        for project in projects:
            logging.info("[{}/{}] validating NetworkPolicies".format(
                cluster, project))
            project_nps = [np for np in network_policies
                           if np['metadata']['namespace'] == project]
            assert len(project_nps) == 2
            assert project_nps[0]['metadata']['name'] != \
                project_nps[1]['metadata']['name']
