import ipaddress
import logging
import sys
from typing import (
    Union,
    cast,
)

from reconcile import queries
from reconcile.gql_definitions.vpc_peerings_validator import vpc_peerings_validator
from reconcile.gql_definitions.vpc_peerings_validator.vpc_peerings_validator import (
    ClusterPeeringConnectionClusterAccepterV1,
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterV1,
    VpcPeeringsValidatorQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "vpc-peerings-validator"


def validate_no_cidr_overlap(
    query_data: VpcPeeringsValidatorQueryData,
) -> bool:
    clusters: list[ClusterV1] = query_data.clusters or []

    for cluster in clusters:
        peerings_enteries_dict = {}  # type: ignore[var-annotated]
        if cluster.peering:
            for peering in cluster.peering.connections:
                if peering.provider == "account-vpc-mesh":
                    aws_account_uid = peering.account.uid  # type: ignore[union-attr]
                    settings = queries.get_secret_reader_settings()
                    accounts = queries.get_aws_accounts(uid=aws_account_uid)
                    awsapi = AWSApi(1, accounts, settings=settings, init_users=False)
                    mesh_results = awsapi.get_vpcs_details(accounts[0])
                    for mesh_result in mesh_results:
                        vpc_peering_info = {
                            "provider": peering.provider,
                            "vpc_peering": {
                                "vpc_name": mesh_result["vpc_id"],
                                "cidr_block": mesh_result["cidr_block"],
                            },
                        }
                        if cluster.name not in peerings_enteries_dict:
                            peerings_enteries_dict[cluster.name] = {
                                "cidr_block": cluster.network.vpc,  # type: ignore[union-attr]
                                "providers": [],
                            }
                            peerings_enteries_dict[cluster.name]["providers"].append(
                                vpc_peering_info
                            )
                if peering.provider == "account-vpc":
                    cidr_block = str(peering.vpc.cidr_block)  # type: ignore[union-attr]
                    vpc_peering_info = {
                        "provider": peering.provider,
                        "vpc_name": peering.vpc.name,  # type: ignore[union-attr]
                        "region": peering.vpc.region,  # type: ignore[union-attr]
                        "cidr_block": cidr_block,
                    }
                    if cluster.name not in peerings_enteries_dict:
                        peerings_enteries_dict[cluster.name] = {
                            "cidr_block": cluster.network.vpc,  # type: ignore[union-attr]
                            "providers": [],
                        }
                    peerings_enteries_dict[cluster.name]["providers"].append(
                        vpc_peering_info
                    )
                if peering.provider in (
                    "cluster-vpc-requester",
                    "cluster-vpc-accepter",
                ):
                    vpc_peering_info = {
                        "provider": peering.provider,
                        "vpc_peering": {
                            "vpc_name": peering.cluster.name,  # type: ignore[union-attr]
                            "cidr_block": peering.cluster.network.vpc,  # type: ignore[union-attr]
                        },
                    }
                    if cluster.name not in peerings_enteries_dict:
                        peerings_enteries_dict[cluster.name] = {
                            "cidr_block": cluster.network.vpc,  # type: ignore[union-attr]
                            "providers": [],
                        }
                    peerings_enteries_dict[cluster.name]["providers"].append(
                        vpc_peering_info
                    )
        overlaps_peering_entries_dict = find_cidr_duplicates_and_overlap(
            peerings_enteries_dict
        )
        if overlaps_peering_entries_dict is False:
            return False
    return True


def find_cidr_duplicates_and_overlap(input_dict: dict):
    cluster_cidr_blocks = []

    items_for_dict = list(input_dict.items())
    for cluster_name, cluster_data in items_for_dict:
        account_vpc_list = []
        account_vpc_mesh_list = []
        cluster_cidr = cluster_data.get("cidr_block")
        cluster_cidr_blocks.append(ipaddress.ip_network(cluster_cidr))
        for cidr_block in cluster_cidr_blocks[:-1]:
            if ipaddress.ip_network(cluster_cidr).overlaps(cidr_block):
                logging.error(
                    f"Cluster {cluster_name} overlaps with CIDR block {cidr_block}"
                )
                return False
        cluster_providers = cluster_data.get("providers")
        for provider in cluster_providers:
            if provider.get("provider") == "account-vpc":
                account_vpc_list.append(
                    ipaddress.ip_network(provider.get("cidr_block"))
                )
            if provider.get("provider") == "account-vpc-mesh":
                account_vpc_mesh_list.append(
                    ipaddress.ip_network(provider.get("cidr_block"))
                )
            if (
                provider.get("provider") == "cluster-vpc-requester"
                or provider.get("provider") == "cluster-vpc-accepter"
            ):
                vpc_peering_compare = provider.get("vpc_peering")
                if ipaddress.ip_network(cluster_cidr).overlaps(
                    ipaddress.ip_network(vpc_peering_compare["cidr_block"])
                ):
                    logging.error(f"VPC peering error in cluster {cluster_name}")
                    logging.error(
                        f"{cluster_name} overlaps with cidr block {vpc_peering_compare['cidr_block']}"
                    )
        for compared_cidr_block, comparing_cidr_blocks in zip(
            account_vpc_list, account_vpc_list[1:]
        ):
            if ipaddress.ip_network(compared_cidr_block).overlaps(
                comparing_cidr_blocks
            ):
                logging.error(f"VPC peering error in cluster {cluster_name}")
                logging.error(
                    f"cidr block {compared_cidr_block} overlaps with another account-vpc with cidr block {comparing_cidr_blocks}"
                )
                return False
        for compared_cidr_block, comparing_cidr_blocks in zip(
            account_vpc_mesh_list, account_vpc_mesh_list[1:]
        ):
            if ipaddress.ip_network(compared_cidr_block).overlaps(
                comparing_cidr_blocks
            ):
                logging.error(f"VPC peering error in cluster {cluster_name}")
                logging.error(
                    f"cidr block {compared_cidr_block} overlaps with another account-vpc with cidr block {comparing_cidr_blocks}"
                )
                return False
    return True


def validate_no_internal_to_public_peerings(
    query_data: VpcPeeringsValidatorQueryData,
) -> bool:
    """Iterate over VPC peerings of internal clusters and validate the peer is not public."""
    valid = True
    found_pairs: list[set[str]] = []
    clusters: list[ClusterV1] = query_data.clusters or []
    for cluster in clusters:
        if not cluster.internal or not cluster.peering:
            continue
        for connection in cluster.peering.connections:
            if connection.provider not in [
                "cluster-vpc-accepter",
                "cluster-vpc-requester",
            ]:
                continue
            connection = cast(
                Union[
                    ClusterPeeringConnectionClusterAccepterV1,
                    ClusterPeeringConnectionClusterRequesterV1,
                ],
                connection,
            )
            peer = connection.cluster
            if peer.internal or (peer.spec and peer.spec.private):
                continue

            valid = False
            pair = {cluster.name, peer.name}
            if pair in found_pairs:
                continue
            found_pairs.append(pair)
            logging.error(
                f"found internal to public vpc peering: {cluster.name} <-> {peer.name}"
            )

    return valid


def validate_no_public_to_public_peerings(
    query_data: VpcPeeringsValidatorQueryData,
) -> bool:
    """Iterate over VPC peerings of public clusters and validate the peer is not public."""
    valid = True
    found_pairs: list[set[str]] = []
    clusters: list[ClusterV1] = query_data.clusters or []
    for cluster in clusters:
        if (
            cluster.internal
            or (cluster.spec and cluster.spec.private)
            or not cluster.peering
        ):
            continue
        for connection in cluster.peering.connections:
            if connection.provider not in [
                "cluster-vpc-accepter",
                "cluster-vpc-requester",
            ]:
                continue
            connection = cast(
                Union[
                    ClusterPeeringConnectionClusterAccepterV1,
                    ClusterPeeringConnectionClusterRequesterV1,
                ],
                connection,
            )
            peer = connection.cluster
            if peer.internal or (peer.spec and peer.spec.private):
                continue

            valid = False
            pair = {cluster.name, peer.name}
            if pair in found_pairs:
                continue
            found_pairs.append(pair)
            logging.error(
                f"found public to public vpc peering: {cluster.name} <-> {peer.name}"
            )

    return valid


def run(dry_run: bool):
    query_data = vpc_peerings_validator.query(query_func=gql.get_api().query)

    valid = True
    if not validate_no_internal_to_public_peerings(query_data):
        valid = False
    if not validate_no_public_to_public_peerings(query_data):
        valid = False
    if not validate_no_cidr_overlap(query_data):
        valid = False

    if not valid:
        sys.exit(ExitCodes.ERROR)
