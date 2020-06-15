import logging
import semver
import sys

import reconcile.queries as queries

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import TerraformClient as Terraform
from utils.defer import defer


QONTRACT_INTEGRATION = 'terraform_aws_route53'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def build_desired_state(zones):
    state = []
    for zone in zones:
        state.append({
            'provider': zone['provider'],
            'account': zone['account'],
            'origin': zone['origin'],
            'default_ttl': zone['default_ttl'],
            'records': zone['records'],
        })
    return state, None


@defer
def run(dry_run=False, print_only=False,
        enable_deletion=False, thread_pool_size=10, defer=None):
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    zones = [z for z in queries.get_dns_zones()
             if z.get('provider') == 'aws-route53']

    desired_state, err = build_desired_state(zones)
    if err:
        logging.error(err)
        sys.exit(1)

    ts = Terrascript(QONTRACT_INTEGRATION,
                     "",
                     thread_pool_size,
                     accounts,
                     settings=settings)
    error = ts.populate_route53(desired_state)
    if error:
        sys.exit(1)
    working_dirs = ts.dump(print_only=print_only)

    if print_only:
        sys.exit()

    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   "",
                   working_dirs,
                   thread_pool_size)

    if tf is None:
        sys.exit(1)

    defer(lambda: tf.cleanup())

    _, err = tf.plan(enable_deletion)
    if err:
        sys.exit(1)

    if dry_run:
        return

    err = tf.apply()
    if err:
        sys.exit(1)
