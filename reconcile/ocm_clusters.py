import sys
import logging

import reconcile.queries as queries

from utils.oc import OC_Map
from utils.ocm import OCMMap

from deepdiff import DeepDiff


QONTRACT_INTEGRATION = 'ocm-clusters'


def current_extended_dedicated_admin_state(oc_map, current_state):
    for cluster in current_state:
        oc = oc_map.get(cluster)
        res = oc.get(None, 'ClusterRole', 'dedicated-admins-manage-operators',
                     allow_not_found=True)
        exists = True if res else False
        current_state[cluster]['spec']['extended_dedicated_admin'] = exists
    return current_state


def run(dry_run=False, thread_pool_size=10, internal=None, use_jump_host=True):
    settings = queries.get_app_interface_settings()
    clusters = queries.get_clusters()
    clusters = [c for c in clusters if c.get('ocm') is not None]
    oc_map = OC_Map(clusters=clusters, integration=QONTRACT_INTEGRATION,
                    settings=settings, internal=internal,
                    use_jump_host=use_jump_host,
                    thread_pool_size=thread_pool_size)
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)

    current_state = ocm_map.cluster_specs()
    current_state = current_extended_dedicated_admin_state(oc_map,
                                                           current_state)

    desired_state = {c['name']: {'spec': c['spec'], 'network': c['network']}
                     for c in clusters}
    for c in desired_state:
        if desired_state[c]['spec'].get('extended_dedicated_admin') is None:
            desired_state[c]['spec']['extended_dedicated_admin'] = False

    error = False
    for cluster, desired_spec in desired_state.items():
        current_spec = current_state[cluster]
        ddiff = DeepDiff(desired_spec, current_spec,
                         ignore_order=True, view='tree')
        if ddiff:
            error = True
            logging.error(
                f'[{cluster}] app-interface (desired) spec is different from '
                f'the spec returned by OCM (current)'
            )
            for changed in ddiff.get('values_changed', []):
                logging.error(f'  path: {changed.path()}')
                logging.error(f'    desired: {changed.t1}')
                logging.error(f'    current: {changed.t2}')

    if error:
        sys.exit(1)
