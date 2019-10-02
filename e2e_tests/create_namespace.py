import time
import logging

import e2e_tests.test_base as tb
import e2e_tests.dedicated_admin_test_base as dat
import e2e_tests.network_policy_test_base as npt

from utils.defer import defer

QONTRACT_E2E_TEST = 'create-namespace'


@defer
def run(defer=None):
    oc_map = tb.get_oc_map(QONTRACT_E2E_TEST)
    defer(lambda: oc_map.cleanup())

    ns_to_create = tb.get_test_namespace_name()
    expected_rolebindings = dat.get_expected_rolebindings()
    expected_network_policies = npt.get_expected_network_policy_names()

    for cluster in oc_map.clusters():
        oc = oc_map.get(cluster)
        logging.info("[{}] Creating namespace '{}'".format(
            cluster, ns_to_create
        ))

        try:
            oc.new_project(ns_to_create)
            time.sleep(5) #  allow time for resources to be created
            for expected_rb in expected_rolebindings:
                rb = oc.get(ns_to_create, 'RoleBinding', expected_rb['name'])
                tb.assert_rolebinding(expected_rb, rb)
            for expected_np in expected_network_policies:
                assert oc.get(ns_to_create, 'NetworkPolicy', expected_np)
        finally:
            logging.info("[{}] Deleting namespace '{}'".format(
                cluster, ns_to_create
            ))
            oc.delete_project(ns_to_create)
