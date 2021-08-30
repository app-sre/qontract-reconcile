import sys
import logging
import copy

from datetime import datetime
from dateutil import parser

import reconcile.queries as queries

from reconcile.utils.ocm import OCMMap
from reconcile.utils.state import State
from reconcile.utils.data_structures import get_or_init

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
            ocm.get_upgrade_policies(cluster_name)
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
        upgrade_policy['current_version'] = cluster['spec']['version']
        desired_state.append(upgrade_policy)

    return desired_state


def update_history(history, upgrade_policies):
    """Update history with information from clusters
    with upgrade policies.

    Args:
        history (dict): history in the following format:
        {
          "check_in": "2021-08-29 18:01:27.730441",
          "versions": {
            "version1": {
                "workloads": {
                    "workload1": {
                        "soak_days": 21,
                        "reporting": [
                            "cluster1",
                            "cluster2"
                        ]
                    },
                        "workload2": {
                        "soak_days": 6,
                        "reporting": [
                            "cluster3"
                        ]
                    }
                }
            }
          }
        }
        upgrade_policies (list): query results of clusters upgrade policies
    """
    default_workload_history = {
        'soak_days': 0.0,
        'reporting': [],
    }

    now = datetime.utcnow()
    check_in = parser.parse(get_or_init(history, 'check_in', str(now)))
    versions = get_or_init(history, 'versions', {})

    # we iterate over clusters upgrade policies and update the version history
    for item in upgrade_policies:
        current_version = item['current_version']
        version_history = get_or_init(versions, current_version, {})
        version_workloads = get_or_init(version_history, 'workloads', {})
        cluster = item['cluster']
        workloads = item['workloads']
        # we keep the version history per workload
        for w in workloads:
            workload_history = get_or_init(
                version_workloads, w,
                copy.deepcopy(default_workload_history))

            reporting = workload_history['reporting']
            # if the cluster is already reporting - accumulate it.
            # if not - add it to the reporting list (first report)
            if cluster in reporting:
                workload_history['soak_days'] += \
                    (now - check_in).total_seconds() / 86400  # seconds in day
            else:
                workload_history['reporting'].append(cluster)

    history['check_in'] = str(now)


def get_version_history(dry_run, upgrade_policies, ocm_map):
    """Get a summary of versions history per OCM instance

    Args:
        dry_run (bool): save updated history to remote state
        upgrade_policies (list): query results of clusters upgrade policies
        ocm_map (OCMMap): OCM clients per OCM instance

    Returns:
        dict: version history per OCM instance
    """
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        settings=settings
    )
    results = {}
    # we keep a remote state per OCM instance
    for ocm_name in ocm_map.instances():
        history = state.get(ocm_name, {})
        update_history(history, upgrade_policies)
        results[ocm_name] = history
        if not dry_run:
            state.add(ocm_name, history, force=True)

    return results


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
    # versions_history = get_version_history(dry_run, desired_state, ocm_map)
    diffs, err = calculate_diff(current_state, desired_state)
    act(dry_run, diffs, ocm_map)

    if err:
        sys.exit(1)
