import sys
import semver
import base64
import logging

import reconcile.utils.gql as gql
import reconcile.utils.threaded as threaded
import reconcile.utils.amtool as amtool
import reconcile.openshift_resources_base as orb

from reconcile.status import ExitCodes

QONTRACT_INTEGRATION = 'alertmanager_config_validator'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)

ALERTMANAGER_SECRET_PATH = '/observability/alertmanager/' \
                           'alertmanager-instance.secret.yaml'
ALERTMANAGER_SECRET_KEY = 'alertmanager.yaml'


def check_config(config):
    '''Helper function to run amtool check-config via threaded.run'''
    config['check_result'] = amtool.check_config(config['data'])
    return config


def get_config_data(namespace_info):
    '''Returns a dict with the alertmanager config from the cluster refered
       in the namespace info'''

    openshift_resources = namespace_info.get('openshiftResources')

    if not openshift_resources:
        return

    for r in openshift_resources:
        path = r['path']
        if path != ALERTMANAGER_SECRET_PATH:
            continue

        openshift_resource = \
            orb.fetch_openshift_resource(resource=r, parent=namespace_info)

        try:
            encoded = openshift_resource.body['data'][ALERTMANAGER_SECRET_KEY]
            data = base64.b64decode(encoded).decode('utf-8')
        except KeyError:
            logging.warning('No data found in config secret for key '
                            f'{ALERTMANAGER_SECRET_KEY}')
            return

        return {'cluster': namespace_info['cluster']['name'], 'data': data}


def run(dry_run, thread_pool_size=20, cluster_name=None):
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    gqlapi = gql.get_api()

    configs = []
    for namespace_info in gqlapi.query(orb.NAMESPACES_QUERY)['namespaces']:
        if namespace_info['name'] != 'openshift-customer-monitoring':
            continue

        if cluster_name and namespace_info['cluster']['name'] != cluster_name:
            continue

        config_data = get_config_data(namespace_info)
        if config_data:
            configs.append(config_data)

    if not configs:
        logging.error(f'No configs found at {ALERTMANAGER_SECRET_PATH}')
        sys.exit(ExitCodes.ERROR)

    result = threaded.run(func=check_config,
                          iterable=configs,
                          thread_pool_size=thread_pool_size)

    failed = [config for config in result if not config['check_result']]

    if failed:
        for f in failed:
            logging.error(f'Error in alertmanager config from cluster '
                          f"{f['cluster']}:  {f['check_result']}")

        sys.exit(ExitCodes.ERROR)
