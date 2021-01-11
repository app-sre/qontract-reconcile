import logging
import re
import semver
import sys

import reconcile.queries as queries

from reconcile.status import ExitCodes

from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript
from reconcile.utils.terraform_client import TerraformClient as Terraform

from reconcile.utils.defer import defer

QONTRACT_INTEGRATION = 'terraform_aws_route53'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def build_desired_state(zones):
    """
    Build the desired state from the app-interface resources

    :param zones: List of zone resources to build state for
    :type zones: list of dict
    :return: State
    :rtype: list of dict
    """

    desired_state = []
    for zone in zones:
        account = zone['account']
        account_name = account['name']

        zone_name = zone['name']
        zone_values = {
            'name': zone_name,
            'account_name': account_name,
            'records': []
        }

        # Check if we have unmanaged_record_names (urn) and compile them
        # all as regular expressions
        urn_compiled = []
        for urn in zone.get('unmanaged_record_names', []):
            urn_compiled.append(re.compile(urn))

        for record in zone['records']:
            record_name = record['name']

            # Check if this record should be ignored
            # as per 'unmanaged_record_names'
            ignored = False
            for regex in urn_compiled:
                if regex.fullmatch(record['name']):
                    logging.debug(f'{zone_name}: excluding unmanaged '
                                  f'record {record_name} because it matched '
                                  f'unmanaged_record_names pattern '
                                  f'\'{regex.pattern}\'')
                    ignored = True
            if ignored:
                continue

            # We use the record object as-is from the list as the terraform
            # data to apply. This makes things simpler and map 1-to-1 with
            # Terraform's capabilities. As such we need to remove (pop) some of
            # the keys we use for our own features

            # Process '_target_cluster'
            target_cluster = record.pop('_target_cluster', None)
            if target_cluster:
                target_cluster_elb = target_cluster['elbFQDN']
                logging.debug(f'{zone_name}: field `_target_cluster` found '
                              f'for record {record_name}. Value will be '
                              f'{target_cluster_elb}')
                record['records'] = [target_cluster_elb]

            # Process '_healthcheck'
            healthcheck = record.pop('_healthcheck', None)
            if healthcheck:
                logging.debug(f'{zone_name}: field `_healthcheck` found '
                              f'for record {record_name}. Values are: '
                              f'{healthcheck}')
                record['healthcheck'] = healthcheck

            zone_values['records'].append(record)

        desired_state.append(zone_values)
    return desired_state


@defer
def run(dry_run=False, print_only=False,
        enable_deletion=False, thread_pool_size=10, defer=None):
    settings = queries.get_app_interface_settings()
    zones = queries.get_dns_zones()

    participating_account_names = [z['account']['name'] for z in zones]
    participating_accounts = [a for a in queries.get_aws_accounts()
                              if a['name'] in participating_account_names]

    ts = Terrascript(QONTRACT_INTEGRATION,
                     "",
                     thread_pool_size,
                     participating_accounts,
                     settings=settings)

    desired_state = build_desired_state(zones)

    error = ts.populate_route53(desired_state)
    if error:
        sys.exit(ExitCodes.ERROR)
    working_dirs = ts.dump(print_only=print_only)

    if print_only:
        sys.exit(ExitCodes.SUCCESS)

    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   "",
                   working_dirs,
                   thread_pool_size)

    if tf is None:
        sys.exit(ExitCodes.ERROR)

    defer(lambda: tf.cleanup())

    _, err = tf.plan(enable_deletion)
    if err:
        sys.exit(ExitCodes.ERROR)

    if dry_run:
        return

    err = tf.apply()
    if err:
        sys.exit(ExitCodes.ERROR)
