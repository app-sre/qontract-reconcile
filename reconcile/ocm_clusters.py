import sys
import logging
import semver

import reconcile.queries as queries

from reconcile import mr_client_gateway
from reconcile.utils.mr.clusters_updates import CreateClustersUpdates

from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-clusters'


def fetch_desired_state(clusters):
    desired_state = {c['name']: {'spec': c['spec'], 'network': c['network']}
                     for c in clusters}
    # remove unused keys
    for desired_spec in desired_state.values():
        # remove empty keys in spec
        desired_spec['spec'] = \
            {k: v for k, v in desired_spec['spec'].items() if v is not None}

    return desired_state


def get_cluster_update_spec(cluster_name, current_spec, desired_spec):
    """ Get a cluster spec to update. Returns an error if diff is invalid """
    allowed_spec_update_fields = {
        'instance_type',
        'storage',
        'load_balancers',
        'private',
        'channel',
        'autoscale',
        'nodes'
    }
    error = False
    if current_spec['network'] != desired_spec['network']:
        error = True
        logging.error(f'[{cluster_name}] invalid update: network')
    current_spec_spec = current_spec['spec']
    desired_spec_spec = desired_spec['spec']
    updated = {k: desired_spec_spec[k] for k in desired_spec_spec
               if current_spec_spec.get(k) != desired_spec_spec[k]}

    # we only need deleted to check if a field removal is valid
    # we really want to check updated + deleted, and since
    # we have no further use for deleted -
    deleted = {k: current_spec_spec[k] for k in current_spec_spec
               if k not in desired_spec_spec}
    diffs = deleted
    diffs.update(updated)

    invalid_fields = set(diffs.keys()) - allowed_spec_update_fields
    if invalid_fields:
        error = True
        logging.error(f'[{cluster_name}] invalid updates: {invalid_fields}')

    return updated, error


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('ocm') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings, init_provision_shards=True)
    current_state, pending_state = ocm_map.cluster_specs()
    desired_state = fetch_desired_state(clusters)

    if not dry_run:
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)

    error = False
    clusters_updates = {}
    for cluster_name, desired_spec in desired_state.items():
        current_spec = current_state.get(cluster_name)
        if current_spec:
            clusters_updates[cluster_name] = {}
            cluster_path = 'data' + \
                [c['path'] for c in clusters
                 if c['name'] == cluster_name][0]

            # validate version
            desired_spec['spec'].pop('initial_version')
            desired_version = desired_spec['spec'].pop('version')
            current_version = current_spec['spec'].pop('version')
            compare_result = 1  # default value in case version is empty
            if desired_version:
                compare_result = \
                    semver.compare(current_version, desired_version)
            if compare_result > 0:
                # current version is larger due to an upgrade.
                # submit MR to update cluster version
                logging.info(
                    '[%s] desired version %s is different ' +
                    'from current version %s. ' +
                    'version will be updated automatically in app-interface.',
                    cluster_name, desired_version, current_version)
                clusters_updates[cluster_name]['version'] = current_version
            elif compare_result < 0:
                logging.error(
                    '[%s] desired version %s is different ' +
                    'from current version %s',
                    cluster_name, desired_version, current_version)
                error = True

            if not desired_spec['spec'].get('id'):
                clusters_updates[cluster_name]['id'] = \
                    current_spec['spec']['id']

            if not desired_spec['spec'].get('external_id'):
                clusters_updates[cluster_name]['external_id'] = \
                    current_spec['spec']['external_id']

            desired_provision_shard_id = \
                desired_spec['spec'].get('provision_shard_id')
            current_provision_shard_id = \
                current_spec['spec']['provision_shard_id']
            if desired_provision_shard_id != current_provision_shard_id:
                clusters_updates[cluster_name]['provision_shard_id'] = \
                    current_provision_shard_id

            if clusters_updates[cluster_name]:
                clusters_updates[cluster_name]['path'] = cluster_path

            # exclude params we don't want to check in the specs
            for k in ['id', 'external_id', 'provision_shard_id']:
                current_spec['spec'].pop(k, None)
                desired_spec['spec'].pop(k, None)

            if current_spec != desired_spec:
                # check if cluster update is valid
                update_spec, err = get_cluster_update_spec(
                    cluster_name,
                    current_spec,
                    desired_spec,
                )
                if err:
                    error = True
                    continue
                # update cluster
                logging.debug(
                    '[%s] desired spec %s is different ' +
                    'from current spec %s',
                    cluster_name, desired_spec, current_spec)
                logging.info(['update_cluster', cluster_name])
                # TODO(mafriedm): check dry_run in OCM API patch
                if not dry_run:
                    ocm = ocm_map.get(cluster_name)
                    ocm.update_cluster(cluster_name, update_spec, dry_run)
        else:
            # create cluster
            if cluster_name in pending_state:
                continue
            logging.info(['create_cluster', cluster_name])
            ocm = ocm_map.get(cluster_name)
            ocm.create_cluster(cluster_name, desired_spec, dry_run)

    create_update_mr = False
    for cluster_name, cluster_updates in clusters_updates.items():
        for k, v in cluster_updates.items():
            if k == 'path':
                continue
            logging.info(
                f"[{cluster_name}] desired key " +
                f"{k} will be updated automatically " +
                f"with value {v}."
            )
            create_update_mr = True
    if create_update_mr and not dry_run:
        mr = CreateClustersUpdates(clusters_updates)
        mr.submit(cli=mr_cli)

    if error:
        sys.exit(1)
