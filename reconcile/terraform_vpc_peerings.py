import semver

import reconcile.queries as queries

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import TerraformClient as Terraform
from utils.ocm import OCMMap


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
        requester = {}
        requester['vpc_id'] = peering_info['vpc_id']
        requester['cidr_block'] = cluster_info['network']['vpc']
        requester['region'] = cluster_info['spec']['region']
        peer_connections = peering_info['connections']
        for peer_vpc in peer_connections:
            # accepter is the peered AWS account
            accepter = {}
            accepter['vpc_id'] = peer_vpc['id']
            accepter['cidr_block'] = peer_vpc['cidr_block']
            accepter['region'] = peer_vpc['region']
            accepter['account'] = peer_vpc['account']
            # assume_role is the role to assume to provision the
            # peering connection request, through the accepter AWS account.
            # this may change in the future -
            # in case we add support for peerings between clusters.
            accepter['account']['assume_role'] = \
                ocm.get_aws_infrastructure_access_terraform_assume_role(
                    cluster,
                    peer_vpc['account']['uid'],
                    peer_vpc['account']['terraformUsername']
                )
            item = {'requester': requester, 'accepter': accepter}
            desired_state.append(item)

    return desired_state


def run(dry_run=False, print_only=False,
        enable_deletion=False, thread_pool_size=10):
    settings = queries.get_app_interface_settings()
    desired_state = fetch_desired_state(settings)
    participating_accounts = \
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
    print(ts.dump())
