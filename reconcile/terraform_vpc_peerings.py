import logging
import sys
import semver
import sys

import reconcile.queries as queries

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import TerraformClient as Terraform
from utils.ocm import OCMMap
from utils.defer import defer


QONTRACT_INTEGRATION = 'terraform_vpc_peerings'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def ensure_matching_cluster_peering(from_cluster, peering, to_cluster,
                                  desired_provider):
    peering_info = to_cluster['peering']
    peer_connections = peering_info['connections']
    for peer_connection in peer_connections:
            if not peer_connection['provider'] == desired_provider:
                continue
            if not peer_connection['cluster']:
                continue
            if from_cluster['name'] == peer_connection['cluster']['name']:
                return True, ""
    msg = f"peering {peering['name']} of type {peering['provider']} " \
          f"for cluster {from_cluster['name']} doesn't have a matching " \
          f"peering type {desired_provider} from cluster {to_cluster['name']}"
    return False, msg

def build_desired_state_cluster(clusters, ocm_map):
    """
    Fetch state for VPC peerings between two clusters
    """
    desired_state = []

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
            # We only care about cluster-vpc-requester peering providers
            if not peer_connection['provider'] == 'cluster-vpc-requester':
                continue

            # Ensure we have a matching peering connection set as cluster-vpc-accepter from the peer cluster
            found, msg = ensure_matching_cluster_peering(cluster_info, peer_connection, peer_connection['cluster'], 'cluster-vpc-accepter')
            if not found:
                return None, msg

            connection_name = peer_connection['name']
            # peer cluster VPC info
            peer_vpc_id = peer_connection['cluster']['peering']['vpc_id']
            peer_vpc_cidr = peer_connection['cluster']['network']['vpc']
            peer_region = peer_connection['cluster']['spec']['region']
            # accepter is the target AWS account VPC
            accepter = {
                'vpc_id': peer_vpc_id,
                'cidr_block': peer_vpc_cidr,
                'region': peer_region,
            }

            # Find an aws account with the "network-mgmt" access level
            awsAccount = None
            for awsAccess in cluster_info['awsInfrastructureAccess']:
                if awsAccess.get('accessLevel', "") == "network-mgmt":
                    awsAccount = {
                        'name': awsAccess['awsGroup']['account']['name'],
                        'uid': awsAccess['awsGroup']['account']['uid'],
                        'terraformUsername': awsAccess['awsGroup']['account']['terraformUsername'],
                    }
            if not awsAccount:
                return None, "could not find an AWS account with the 'network-mgmt' access level on the cluster"
            
            # find role to use for aws access
            awsAccount['assume_role'] = \
                ocm.get_aws_infrastructure_access_terraform_assume_role(
                    cluster,
                    awsAccount['uid'],
                    awsAccount['terraformUsername']
                )
            awsAccount['assume_region'] = peer_region
            item = {
                'connection_name': connection_name,
                'requester': requester,
                'accepter': accepter,
                'account': awsAccount
            }

            desired_state.append(item)

    return desired_state, None

def build_desired_state_vpc(clusters, ocm_map):
    """
    Fetch state for VPC peerings between a cluster and a VPC (account)
    """
    desired_state = []

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
            # We only care about account-vpc peering providers
            if not peer_connection['provider'] == 'account-vpc':
                continue
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
            # assume_region is the region in which the requester resides
            account['assume_region'] = requester['region']
            item = {
                'connection_name': connection_name,
                'requester': requester,
                'accepter': accepter,
                'account': account
            }
            desired_state.append(item)
    return desired_state, None

@defer
def run(dry_run=False, print_only=False,
        enable_deletion=False, thread_pool_size=10, defer=None):
    settings = queries.get_app_interface_settings()
    clusters = [c for c in queries.get_clusters()
                if c.get('peering') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)

    # Fetch desired state for cluster-to-vpc(account) VPCs
    desired_state_vpc, err = build_desired_state_vpc(clusters, ocm_map)
    if err:
        logging.error(err)
        sys.exit(1)

    # Fetch desired state for cluster-to-cluster VPCs
    desired_state_cluster, err = build_desired_state_cluster(clusters, ocm_map)
    if err:
        logging.error(err)
        sys.exit(1)

    desired_state = desired_state_vpc + desired_state_cluster

    # check there are no repeated vpc connection names
    connection_names = [c['connection_name'] for c in desired_state]
    if len(set(connection_names)) != len(connection_names):
        logging.error("duplicated vpc connection names found")

    participating_accounts = [item['account'] for item in desired_state]
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
