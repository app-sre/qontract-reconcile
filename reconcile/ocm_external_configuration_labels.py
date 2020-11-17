import sys
import logging
import json

import reconcile.queries as queries

from reconcile.status import ExitCodes
from utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-external-configuration-labels'


def fetch_current_state(clusters):
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)

    current_state = []
    for cluster in clusters:
        cluster_name = cluster['name']
        ocm = ocm_map.get(cluster_name)
        labels = ocm.get_external_configuration_labels(cluster_name)
        labels['cluster'] = cluster_name
        current_state.append(labels)

    return ocm_map, current_state


def fetch_desired_state(clusters):
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster['name']
        labels = json.loads(cluster['externalConfiguration']['labels'])
        labels['cluster'] = cluster_name
        desired_state.append(labels)

    return desired_state


def calculate_diff(current_state, desired_state):
    diffs = []
    err = False
    for d in desired_state:
        c = [c for c in current_state if d['cluster'] == c['cluster']]
        if not c:
            d['action'] = 'create'
            diffs.append(d)
            continue
        if len(c) != 1:
            logging.error(f"duplicate id found in {d['cluster']}")
            err = True
            continue
        c = c[0]
        if d != c:
            d['action'] = 'update'
            diffs.append(d)

    for c in current_state:
        d = [d for d in desired_state if c['cluster'] == d['cluster']]
        if not d:
            c['action'] = 'delete'
            diffs.append(c)

    return diffs, err


def act(dry_run, diffs, ocm_map):
    for diff in diffs:
        action = diff.pop('action')
        cluster = diff.pop('cluster')
        logging.info([action, cluster, diff['id']])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            if action == 'create':
                ocm.create_external_configuration_labels(cluster, diff)
            # elif action == 'update':
            #     ocm.update_machine_pool(cluster, diff)
            # elif action == 'delete':
            #     ocm.delete_machine_pool(cluster, diff)


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    clusters = queries.get_clusters()
    clusters = [c for c in clusters
                if c.get('externalConfiguration') is not None]
    if not clusters:
        logging.debug(
            "No externalConfiguration definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state = fetch_current_state(clusters)
    desired_state = fetch_desired_state(clusters)
    diffs, err = calculate_diff(current_state, desired_state)
    act(dry_run, diffs, ocm_map)

    if err:
        sys.exit(ExitCodes.ERROR)
