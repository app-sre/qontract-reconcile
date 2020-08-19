import sys
import logging
import semver

import reconcile.queries as queries
import reconcile.pull_request_gateway as prg

from utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-clusters'


def fetch_current_state(clusters):
    desired_state = {c['name']: {'spec': c['spec'], 'network': c['network']}
                     for c in clusters}
    # remove unused keys
    for desired_spec in desired_state.values():
        desired_spec['spec'].pop('upgrade', None)

    return desired_state


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('ocm') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)
    current_state, pending_state = ocm_map.cluster_specs()
    desired_state = fetch_current_state(clusters)

    if not dry_run:
        gw = prg.init(gitlab_project_id=gitlab_project_id)
    error = False
    for cluster_name, desired_spec in desired_state.items():
        current_spec = current_state.get(cluster_name)
        if current_spec:
            cluster_path = 'data' + \
                [c['path'] for c in clusters
                 if c['name'] == cluster_name][0]

            # validate version
            desired_spec['spec'].pop('initial_version')
            desired_version = desired_spec['spec'].pop('version')
            current_version = current_spec['spec'].pop('version')
            compare_result = semver.compare(current_version, desired_version)
            if compare_result > 0:
                # current version is larger due to an upgrade.
                # submit MR to update cluster version
                logging.info(
                    '[%s] desired version %s is different ' +
                    'from current version %s. ' +
                    'version will be updated automatically in app-interface.',
                    cluster_name, desired_version, current_version)
                if not dry_run:
                    gw.create_update_cluster_version_mr(
                        cluster_name, cluster_path, current_version)
            elif compare_result < 0:
                logging.error(
                    '[%s] desired version %s is different ' +
                    'from current version %s',
                    cluster_name, desired_version, current_version)
                error = True

            # id and external_id are present
            if not desired_spec.get('id') or \
                    not desired_spec.get('external_id'):
                cluster_id = current_spec['spec']['id']
                cluster_external_id = current_spec['spec']['external_id']
                logging.info(
                    f'[{cluster_name}] is missing id: {cluster_id}, ' +
                    f'and external_id: {cluster_external_id}. ' +
                    'It will be updated automatically in app-interface.')
                if not dry_run:
                    gw.create_update_cluster_ids_mr(cluster_name, cluster_path,
                                                    cluster_id,
                                                    cluster_external_id)
            # validate specs
            if current_spec != desired_spec:
                logging.error(
                    '[%s] desired spec %s is different ' +
                    'from current spec %s',
                    cluster_name, desired_spec, current_spec)
                error = True
        else:
            # create cluster
            if cluster_name in pending_state:
                continue
            logging.info(['create_cluster', cluster_name])
            if not dry_run:
                ocm = ocm_map.get(cluster_name)
                ocm.create_cluster(cluster_name, desired_spec)

    if error:
        sys.exit(1)
