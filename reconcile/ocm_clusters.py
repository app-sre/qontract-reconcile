import sys
import logging

import reconcile.queries as queries

from utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-clusters'


def run(dry_run, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('ocm') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)
    current_state, pending_state = ocm_map.cluster_specs()
    desired_state = {c['name']: {'spec': c['spec'], 'network': c['network']}
                     for c in clusters}

    error = False
    for cluster_name, desired_spec in desired_state.items():
        current_spec = current_state.get(cluster_name)
        if current_spec and current_spec != desired_spec:
            logging.error(
                '[%s] desired spec %s is different from current spec %s',
                cluster_name, desired_spec, current_spec)
            error = True

    if error:
        sys.exit(1)

    for cluster_name, desired_spec in desired_state.items():
        if cluster_name in current_state or cluster_name in pending_state:
            continue
        logging.info(['create_cluster', cluster_name])
        if not dry_run:
            ocm = ocm_map.get(cluster_name)
            ocm.create_cluster(cluster_name, desired_spec)
