import time
import logging

from sretoolbox.utils import threaded

import e2e_tests.test_base as tb
import e2e_tests.dedicated_admin_test_base as dat
import e2e_tests.network_policy_test_base as npt

from reconcile.utils.defer import defer

QONTRACT_E2E_TEST = "create-namespace"


def test_cluster(cluster, oc_map, ns_under_test, dry_run):
    oc = oc_map.get(cluster)
    logging.info("[{}] Creating namespace '{}'".format(cluster, ns_under_test))

    if not dry_run:
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
def run(thread_pool_size=10, dry_run=False, defer=None):
    oc_map = tb.get_oc_map(QONTRACT_E2E_TEST)
    defer(oc_map.cleanup)
    ns_under_test = tb.get_test_namespace_name()
    threaded.run(
        test_cluster,
        oc_map.clusters(),
        thread_pool_size,
        oc_map=oc_map,
        ns_under_test=ns_under_test,
        dry_run=dry_run,
    )
