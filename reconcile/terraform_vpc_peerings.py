import sys
import semver

import reconcile.queries as queries

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import TerraformClient as Terraform
from utils.ocm import OCMMap
from utils.defer import defer


QONTRACT_INTEGRATION = 'terraform_vpc_peerings'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def fetch_desired_state(settings):
    desired_state = []
    clusters = [c for c in queries.get_clusters()
                if c.get('peering') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)
    for cluster_info in clusters:
        cluster = cluster_info['name']
        ocm = ocm_map.get(cluster)
        peering_info = cluster_info['peering']
        # requester is the cluster's AWS account
        requester = {
            'vpc_id': peering_info['vpc_id'],
            'cidr_block': cluster_info['network']['vpc'],
            'region': cluster_info['spec']['region']
        }
        peer_connections = peering_info['connections']
        for peer_connection in peer_connections:
            connection_name = peer_connection['name']
            peer_vpc = peer_connection['vpc']
            # accepter is the peered AWS account
            accepter = {
                'vpc_id': peer_vpc['vpc_id'],
                'cidr_block': peer_vpc['cidr_block'],
                'region': peer_vpc['region']
            }
            account = peer_vpc['account']
            # assume_role is the role to assume to provision the
            # peering connection request, through the accepter AWS account.
            # this may change in the future -
            # in case we add support for peerings between clusters.
            account['assume_role'] = \
                ocm.get_aws_infrastructure_access_terraform_assume_role(
                    cluster,
                    peer_vpc['account']['uid'],
                    peer_vpc['account']['terraformUsername']
                )
            item = {
                'connection_name': connection_name,
                'requester': requester,
                'accepter': accepter,
                'account': account
            }
            desired_state.append(item)

    return desired_state


@defer
def run(dry_run=False, print_only=False,
        enable_deletion=False, thread_pool_size=10, defer=None):
    settings = queries.get_app_interface_settings()
    desired_state = fetch_desired_state(settings)
    participating_accounts = \
        [item['account'] for item in desired_state]
    participating_account_names = \
        [a['name'] for a in participating_accounts]
    accounts = [a for a in queries.get_aws_accounts()
                if a['name'] in participating_account_names]

    ts = Terrascript(QONTRACT_INTEGRATION,
                     "",
                     thread_pool_size,
                     accounts,
                     settings=settings)
    ts.populate_additional_providers(participating_accounts)
    ts.populate_vpc_peerings(desired_state)
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

    deletions_detected, err = tf.plan(enable_deletion)
    if err:
        sys.exit(1)
    if deletions_detected and not enable_deletion:
        sys.exit(1)

    if dry_run:
        return

    err = tf.apply()
    if err:
        sys.exit(1)
