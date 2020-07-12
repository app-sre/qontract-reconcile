import logging
import semver
import sys

import reconcile.queries as queries

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import TerraformClient as Terraform
from utils.aws_api import AWSApi
from utils.ocm import OCMMap
from utils.defer import defer


QONTRACT_INTEGRATION = 'terraform_vpc_peerings'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def find_matching_peering(from_cluster, peering, to_cluster, desired_provider):
    """
    Ensures there is a matching peering with the desired provider type
    going from the destination (to) cluster back to this one (from)
    """
    peering_info = to_cluster['peering']
    peer_connections = peering_info['connections']
    for peer_connection in peer_connections:
            if not peer_connection['provider'] == desired_provider:
                continue
            if not peer_connection['cluster']:
                continue
            if from_cluster['name'] == peer_connection['cluster']['name']:
                return peer_connection
    return None


def aws_account_from_infrastructure_access(cluster, access_level, ocm_map):
    """
    Generate an AWS account object from a cluster's awsInfrastructureAccess
    groups and access levels
    """
    ocm = ocm_map.get(cluster['name'])
    account = None
    for awsAccess in cluster['awsInfrastructureAccess']:
        if awsAccess.get('accessLevel', "") == access_level:
            account = {
                'name': awsAccess['awsGroup']['account']['name'],
                'uid': awsAccess['awsGroup']['account']['uid'],
                'terraformUsername':
                    awsAccess['awsGroup']['account']['terraformUsername'],
                'automationToken':
                    awsAccess['awsGroup']['account']['automationToken'],
                'assume_role':
                    ocm.get_aws_infrastructure_access_terraform_assume_role(
                        cluster['name'],
                        awsAccess['awsGroup']['account']['uid'],
                        awsAccess['awsGroup']['account']['terraformUsername'],
                    )
            }
    return account


def build_desired_state_cluster(clusters, ocm_map, settings):
    """
    Fetch state for VPC peerings between two OCM clusters
    """
    desired_state = []
    error = False

    for cluster_info in clusters:
        cluster_name = cluster_info['name']

        # Find an aws account with the "network-mgmt" access level on the
        # requester cluster and use that as the account for the requester
        req_aws = aws_account_from_infrastructure_access(cluster_info,
                                                         'network-mgmt',
                                                         ocm_map)
        if not req_aws:
            msg = f"could not find an AWS account with the " \
                  f"'network-mgmt' access level on the cluster {cluster_name}"
            logging.error(msg)
            error = True
            continue
        req_aws['assume_region'] = cluster_info['spec']['region']
        req_aws['assume_cidr'] = cluster_info['network']['vpc']

        peering_info = cluster_info['peering']
        peer_connections = peering_info['connections']
        for peer_connection in peer_connections:
            # We only care about cluster-vpc-requester peering providers
            if not peer_connection['provider'] == 'cluster-vpc-requester':
                continue

            peer_connection_name = peer_connection['name']
            peer_cluster = peer_connection['cluster']
            peer_cluster_name = peer_cluster['name']

            # Ensure we have a matching peering connection
            peer_info = find_matching_peering(cluster_info,
                                              peer_connection,
                                              peer_cluster,
                                              'cluster-vpc-accepter')
            if not peer_info:
                msg = f"could not find a matching peering connection for " \
                      f"cluster {cluster_name}, " \
                      f"connection {peer_connection_name}"
                logging.error(msg)
                error = True
                continue

            aws_api = AWSApi(1, [req_aws], settings=settings)
            requester_vpc_id = aws_api.get_cluster_vpc_id(req_aws)
            if requester_vpc_id is None:
                msg = f'[{cluster_name} could not find VPC ID for cluster'
                logging.error(msg)
                error = True
                continue
            requester = {
                'cidr_block': cluster_info['network']['vpc'],
                'region': cluster_info['spec']['region'],
                'vpc_id': requester_vpc_id,
                'account': req_aws
            }

            # Find an aws account with the "network-mgmt" access level on the
            # peer cluster and use that as the account for the accepter
            acc_aws = aws_account_from_infrastructure_access(peer_cluster,
                                                             'network-mgmt',
                                                             ocm_map)
            if not acc_aws:
                msg = "could not find an AWS account with the " \
                    "'network-mgmt' access level on the cluster"
                logging.error(msg)
                error = True
                continue
            acc_aws['assume_region'] = peer_cluster['spec']['region']
            acc_aws['assume_cidr'] = peer_cluster['network']['vpc']

            aws_api = AWSApi(1, [acc_aws], settings=settings)
            accepter_vpc_id = aws_api.get_cluster_vpc_id(acc_aws)
            if accepter_vpc_id is None:
                msg = f'[{peer_cluster_name} could not find VPC ID for cluster'
                logging.error(msg)
                error = True
                continue
            requester['peer_owner_id'] = acc_aws['assume_role'].split(':')[4]
            accepter = {
                'cidr_block': peer_cluster['network']['vpc'],
                'region': peer_cluster['spec']['region'],
                'vpc_id': accepter_vpc_id,
                'account': acc_aws
            }

            item = {
                'connection_name': peer_connection['name'],
                'requester': requester,
                'accepter': accepter,
            }
            desired_state.append(item)

    return desired_state, error


def build_desired_state_vpc(clusters, ocm_map, settings):
    """
    Fetch state for VPC peerings between a cluster and a VPC (account)
    """
    desired_state = []
    error = False

    for cluster_info in clusters:
        cluster = cluster_info['name']
        ocm = ocm_map.get(cluster)
        peering_info = cluster_info['peering']
        peer_connections = peering_info['connections']
        for peer_connection in peer_connections:
            # requester is the cluster's AWS account
            requester = {
                'cidr_block': cluster_info['network']['vpc'],
                'region': cluster_info['spec']['region']
            }
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
            account['assume_region'] = requester['region']
            account['assume_cidr'] = requester['cidr_block']
            aws_api = AWSApi(1, [account], settings=settings)
            requester_vpc_id = aws_api.get_cluster_vpc_id(account)
            if requester_vpc_id is None:
                logging.error(f'[{cluster} could not find VPC ID for cluster')
                error = True
                continue
            requester['vpc_id'] = requester_vpc_id
            requester['account'] = account
            accepter['account'] = account
            item = {
                'connection_name': connection_name,
                'requester': requester,
                'accepter': accepter,
            }
            desired_state.append(item)
    return desired_state, error


@defer
def run(dry_run, print_only=False,
        enable_deletion=False, thread_pool_size=10, defer=None):
    settings = queries.get_app_interface_settings()
    clusters = [c for c in queries.get_clusters()
                if c.get('peering') is not None]
    ocm_map = OCMMap(clusters=clusters, integration=QONTRACT_INTEGRATION,
                     settings=settings)

    # Fetch desired state for cluster-to-vpc(account) VPCs
    desired_state_vpc, err = \
        build_desired_state_vpc(clusters, ocm_map, settings)
    if err:
        sys.exit(1)

    # Fetch desired state for cluster-to-cluster VPCs
    desired_state_cluster, err = \
        build_desired_state_cluster(clusters, ocm_map, settings)
    if err:
        sys.exit(1)

    desired_state = desired_state_vpc + desired_state_cluster

    # check there are no repeated vpc connection names
    connection_names = [c['connection_name'] for c in desired_state]
    if len(set(connection_names)) != len(connection_names):
        logging.error("duplicate vpc connection names found")
        sys.exit(1)

    participating_accounts = \
        [item['requester']['account'] for item in desired_state]
    participating_accounts += \
        [item['accepter']['account'] for item in desired_state]
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
