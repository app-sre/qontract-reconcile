import sys
import logging

import reconcile.queries as queries

from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-upgrade-scheduler'


def fetch_current_state(clusters):
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)

    current_state = []
    for cluster in clusters:
        cluster_name = cluster['name']
        ocm = ocm_map.get(cluster_name)
        upgrade_policies = \
            ocm.get_upgrade_policies(cluster_name, schedule_type='automatic')
        for upgrade_policy in upgrade_policies:
            upgrade_policy['cluster'] = cluster_name
            current_state.append(upgrade_policy)

    return ocm_map, current_state


def fetch_desired_state(clusters):
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster['name']
        upgrade_policy = cluster['upgradePolicy']
        upgrade_policy['cluster'] = cluster_name
        desired_state.append(upgrade_policy)

    return desired_state


def calculate_diff(current_state, desired_state):
    diffs = []
    err = False
    for d in desired_state:
        c = [c for c in current_state
             if d.items() <= c.items()]
        if not c:
            d['action'] = 'create'
            diffs.append(d)

    for c in current_state:
        d = [d for d in desired_state
             if d.items() <= c.items()]
        if not d:
            c['action'] = 'delete'
            diffs.append(c)

    return diffs, err


def sort_diffs(diff):
    if diff['action'] == 'delete':
        return 1
    else:
        return 2


def act(dry_run, diffs, ocm_map):
    diffs.sort(key=sort_diffs)
    for diff in diffs:
        action = diff.pop('action')
        cluster = diff.pop('cluster')
        logging.info([action, cluster])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            if action == 'create':
                ocm.create_upgrade_policy(cluster, diff)
            elif action == 'delete':
                ocm.delete_upgrade_policy(cluster, diff)


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('upgradePolicy') is not None]
    if not clusters:
        logging.debug("No upgradePolicy definitions found in app-interface")
        sys.exit(0)

    ocm_map, current_state = fetch_current_state(clusters)
    desired_state = fetch_desired_state(clusters)
    diffs, err = calculate_diff(current_state, desired_state)
    act(dry_run, diffs, ocm_map)

    if err:
        sys.exit(1)
