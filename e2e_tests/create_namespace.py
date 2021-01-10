import time
import logging

import e2e_tests.test_base as tb
import e2e_tests.dedicated_admin_test_base as dat
import e2e_tests.network_policy_test_base as npt
import reconcile.utils.threaded as threaded

from reconcile.utils.defer import defer

QONTRACT_E2E_TEST = 'create-namespace'


def test_cluster(cluster, oc_map, ns_under_test):
    oc = oc_map.get(cluster)
    logging.info("[{}] Creating namespace '{}'".format(
        cluster, ns_under_test
    ))

    try:
        oc.new_project(ns_under_test)
        time.sleep(5)  # allow time for resources to be created
        dat.test_project_admin_rolebindings(oc, ns_under_test)
        npt.test_project_network_policies(oc, ns_under_test)
    except Exception:
        logging.error(f"[{cluster}] failed test {QONTRACT_E2E_TEST}")
    finally:
        logging.info(f"[{cluster}] Deleting namespace '{ns_under_test}'")
        oc.delete_project(ns_under_test)


@defer
def run(thread_pool_size=10, defer=None):
    oc_map = tb.get_oc_map(QONTRACT_E2E_TEST)
    defer(lambda: oc_map.cleanup())
    ns_under_test = tb.get_test_namespace_name()
    threaded.run(test_cluster, oc_map.clusters(), thread_pool_size,
                 oc_map=oc_map,
                 ns_under_test=ns_under_test)
