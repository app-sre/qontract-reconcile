import sys
import logging
import semver

import reconcile.queries as queries

from reconcile import mr_client_gateway
from utils.mr import CreateUpdateClusterIds
from utils.mr import CreateUpdateClusterVersion

from utils.ocm import OCMMap

QONTRACT_INTEGRATION = 'ocm-machine-pools'


# def fetch_current_state(clusters):
#     desired_state = {c['name']: {'spec': c['spec'], 'network': c['network']}
#                      for c in clusters}
#     # remove unused keys
#     for desired_spec in desired_state.values():
#         desired_spec['spec'].pop('upgrade', None)

#     return desired_state


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('ocm') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)

    for cluster in clusters:
        cluster_name = cluster['name']
        ocm = ocm_map.get(cluster_name)
        machine_pools = ocm.get_machine_pools(cluster_name)
        

    import sys
    sys.exit()

    # current_state, pending_state = ocm_map.cluster_specs()
    # desired_state = fetch_current_state(clusters)

    # if not dry_run:
    #     mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)

    # error = False
    # for cluster_name, desired_spec in desired_state.items():
    #     current_spec = current_state.get(cluster_name)
    #     if current_spec:
    #         cluster_path = 'data' + \
    #             [c['path'] for c in clusters
    #              if c['name'] == cluster_name][0]

    #         # validate version
    #         desired_spec['spec'].pop('initial_version')
    #         desired_version = desired_spec['spec'].pop('version')
    #         current_version = current_spec['spec'].pop('version')
    #         compare_result = 1  # default value in case version is empty
    #         if desired_version:
    #             compare_result = \
    #                 semver.compare(current_version, desired_version)
    #         if compare_result > 0:
    #             # current version is larger due to an upgrade.
    #             # submit MR to update cluster version
    #             logging.info(
    #                 '[%s] desired version %s is different ' +
    #                 'from current version %s. ' +
    #                 'version will be updated automatically in app-interface.',
    #                 cluster_name, desired_version, current_version)
    #             if not dry_run:
    #                 mr = CreateUpdateClusterVersion(cluster_name, cluster_path,
    #                                                 current_version)
    #                 mr.submit(cli=mr_cli)
    #         elif compare_result < 0:
    #             logging.error(
    #                 '[%s] desired version %s is different ' +
    #                 'from current version %s',
    #                 cluster_name, desired_version, current_version)
    #             error = True

    #         # id and external_id are present
    #         if not desired_spec['spec'].get('id') or \
    #                 not desired_spec['spec'].get('external_id'):
    #             cluster_id = current_spec['spec']['id']
    #             external_id = current_spec['spec']['external_id']
    #             logging.info(
    #                 f'[{cluster_name}] is missing id: {cluster_id}, ' +
    #                 f'and external_id: {external_id}. ' +
    #                 'It will be updated automatically in app-interface.')
    #             if not dry_run:
    #                 mr = CreateUpdateClusterIds(cluster_name, cluster_path,
    #                                             cluster_id, external_id)
    #                 mr.submit(cli=mr_cli)

    #         # exclude params we don't want to check in the specs
    #         for k in ['id', 'external_id', 'provision_shard_id']:
    #             current_spec['spec'].pop(k, None)
    #             desired_spec['spec'].pop(k, None)

    #         # validate specs
    #         if current_spec != desired_spec:
    #             logging.error(
    #                 '[%s] desired spec %s is different ' +
    #                 'from current spec %s',
    #                 cluster_name, desired_spec, current_spec)
    #             error = True
    #     else:
    #         # create cluster
    #         if cluster_name in pending_state:
    #             continue
    #         logging.info(['create_cluster', cluster_name])
    #         if not dry_run:
    #             ocm = ocm_map.get(cluster_name)
    #             ocm.create_cluster(cluster_name, desired_spec)

    # if error:
    #     sys.exit(1)
