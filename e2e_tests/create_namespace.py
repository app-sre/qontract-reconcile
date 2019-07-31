import sys
import time
import datetime
import logging

from e2e_tests.test_base import get_oc_map
from e2e_tests.dedicated_admin_test_base import get_expected_rolebindings


def run_create_namespace_test():
    oc_map = get_oc_map()

    ns_to_create = 'create-namespace-test-{}'.format(
        datetime.datetime.utcnow().strftime('%Y%m%d%H%M')
    )
    expected_rolebindings = get_expected_rolebindings()
    for cluster, oc in oc_map.items():
        logging.info("[{}] Creating namespace '{}'".format(
            cluster, ns_to_create
        ))

        try:
            oc.new_project(ns_to_create)
            time.sleep(2) #  allow time for RoleBindings to be created
            for expected_rb in expected_rolebindings:
                rb = oc.get(ns_to_create, 'RoleBinding', expected_rb['name'])
                rb_roleref_name = rb['roleRef']['name']
                assert rb_roleref_name == expected_rb['role']
                rb_group_names = rb['groupNames']
                assert rb_group_names == expected_rb['groups']
        finally:
            logging.info("[{}] Deleting namespace '{}'".format(
                cluster, ns_to_create
            ))
            oc.delete_project(ns_to_create)


def run():
    run_create_namespace_test()
