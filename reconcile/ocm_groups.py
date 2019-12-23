import logging

import utils.threaded as threaded
import reconcile.queries as queries
import reconcile.openshift_groups as openshift_groups

from utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-groups'


def fetch_current_state(thread_pool_size):
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('ocm') is not None]
    current_state = []
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)
    groups_list = openshift_groups.create_groups_list(clusters, oc_map=ocm_map)
    print(groups_list)
    import sys
    sys.exit()
    results = threaded.run(openshift_groups.get_cluster_state, groups_list,
                           thread_pool_size, oc_map=ocm_map)

    current_state = [item for sublist in results for item in sublist]
    return ocm_map, current_state


def run(dry_run=False, thread_pool_size=10):
    ocm_map, current_state = fetch_current_state(thread_pool_size)
    desired_state = openshift_groups.fetch_desired_state(oc_map=ocm_map)

    diffs = openshift_groups.calculate_diff(current_state, desired_state)
    openshift_groups.validate_diffs(diffs)

    for diff in diffs:
        if diff['action'] in ["create_group", "delete_group"]:
            logging.error("can not create or delete groups via OCM")
            logging.error(list(diff.values()))
            continue

        logging.info(list(diff.values()))

        if not dry_run:
            openshift_groups.act(diff, oc_map=ocm_map)
