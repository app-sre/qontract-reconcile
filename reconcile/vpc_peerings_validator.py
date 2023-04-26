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

    cidr_block_entries_acount_vpc = {}
    cidr_block_entries_acount_vpc_mesh = {}
    cidr_block_entries_cluster_vpc = {}
    cidr_block_entries_requester = {}
    cidr_block_entries_accepter = {}
    for cluster in clusters:
        # This block shouldn't be here, need to fix
        try:
            cidr_block = str(cluster.network.vpc)  # type: ignore[union-attr]
            cidr_block_entries_cluster_vpc[cluster.name] = cidr_block
        except AttributeError:
            continue
        if cluster.peering:
            for peering in cluster.peering.connections:
                if peering.provider == "account-vpc":
                    cidr_block = str(peering.vpc.cidr_block)  # type: ignore[union-attr]
                    cidr_block_entries_acount_vpc[peering.vpc.name] = cidr_block  # type: ignore[union-attr]
                if peering.provider == "account-vpc-mesh":
                    tags_dict = peering.tags  # type: ignore[union-attr]
                    aws_account_uid = peering.account.uid  # type: ignore[union-attr]
                    for tags_key, tags_value in tags_dict.items():  # type: ignore[union-attr]
                        settings = queries.get_secret_reader_settings()
                        accounts = queries.get_aws_accounts(uid=aws_account_uid)
                        awsapi = AWSApi(
                            1, accounts, settings=settings, init_users=False
                        )
                        cidr_block_entries_acount_vpc_mesh = cidr_mesh_finder(
                            aws_account_uid, tags_key, tags_value, awsapi
                        )
                if peering.provider == "cluster-vpc-requester":
                    cidr_block = str(peering.cluster.network.vpc)  # type: ignore[union-attr]
                    cidr_block_entries_requester[peering.cluster.name] = cidr_block  # type: ignore[union-attr]
                if peering.provider == "cluster-vpc-accepter":
                    cidr_block = str(peering.cluster.network.vpc)  # type: ignore[union-attr]
                    cidr_block_entries_accepter[peering.cluster.name] = cidr_block  # type: ignore[union-attr]

        overlaps_account_vpc = find_cidr_duplicates_and_overlap(
            cidr_block_entries_acount_vpc
        )
        if overlaps_account_vpc:
            logging.error("VPC peering error for cluster %s", cluster)
            return False
        overlaps_account_vpc_mesh = find_cidr_duplicates_and_overlap(
            cidr_block_entries_acount_vpc_mesh
        )
        if overlaps_account_vpc_mesh:
            logging.error("VPC peering error for cluster %s", cluster)
            return False
        overlaps_account_requester = find_cidr_duplicates_and_overlap(
            cidr_block_entries_requester
        )
        if overlaps_account_requester:
            logging.error("VPC peering error for cluster %s", cluster)
            return False
        overlaps_account_accepter = find_cidr_duplicates_and_overlap(
            cidr_block_entries_accepter
        )
        if overlaps_account_accepter:
            logging.error("VPC peering error for cluster %s", cluster)
            return False
    overlaps_account_cluster_vpc = find_cidr_duplicates_and_overlap(
        cidr_block_entries_cluster_vpc
    )
    if overlaps_account_cluster_vpc:
        return False

    return True


def cidr_mesh_finder(aws_account_uid, tag_key, tag_value: str, awsapi: AWSApi):
    # settings = queries.get_secret_reader_settings()
    accounts = queries.get_aws_accounts(uid=aws_account_uid)
    # awsapi = AWSApi(1, accounts, settings=settings, init_users=False)
    comparing_vpc_dict, mesh_vpc_dict = awsapi.get_mesh_vpc_peerings(
        accounts, tag_key, tag_value
    )
    final_dict = compare_cidr_with_cidr_dict(comparing_vpc_dict, mesh_vpc_dict)
    # awsapi.create_route53_zone
    return final_dict


def compare_cidr_with_cidr_dict(compared_dict, comparing_dict):
    overlaps_list = []
    for compared_vpc, mesh_cidr_compared in compared_dict.items():
        for comparing_vpc, mesh_cidr_comparing in comparing_dict.items():
            if ipaddress.ip_network(mesh_cidr_compared).overlaps(
                ipaddress.ip_network(mesh_cidr_comparing)
            ):
                overlaps_list.append((compared_vpc, comparing_vpc, mesh_cidr_compared))
    if overlaps_list:
        logging.error("Overlapping CIDR blocks found:")
        for compared_vpc, comparing_vpc, cidr_block in overlaps_list:
            logging.error(
                "VPC %s with CIDR block %s overlaps with VPC %s with CIDR block %s",
                compared_vpc,
                cidr_block,
                comparing_vpc,
                comparing_dict[comparing_vpc],
            )
    return overlaps_list


def find_cidr_duplicates_and_overlap(input_dict: dict):
    overlaps_list = []

    keys_for_dict = list(input_dict.keys())
    for i, compared_vpc in enumerate(keys_for_dict):
        for comparing_vpc in keys_for_dict[i + 1 :]:
            if input_dict[compared_vpc] == input_dict[comparing_vpc]:
                overlaps_list.append((compared_vpc, comparing_vpc))
            elif ipaddress.ip_network(input_dict[compared_vpc]).overlaps(
                ipaddress.ip_network(input_dict[comparing_vpc])
            ):
                overlaps_list.append((compared_vpc, comparing_vpc))

    for compared_vpc, comparing_vpc in overlaps_list:
        if input_dict[compared_vpc] == input_dict[comparing_vpc]:
            logging.error(
                "VPC %s with network %s has the same network as VPC %s",
                compared_vpc,
                input_dict[compared_vpc],
                comparing_vpc,
            )
        else:
            logging.error(
                "VPC %s with network %s overlaps with VPC %s with network %s",
                compared_vpc,
                input_dict[compared_vpc],
                comparing_vpc,
                input_dict[comparing_vpc],
            )

    # return duplicates, overlaps_list
    return overlaps_list


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
            if peer.internal or (peer.spec and peer.spec.private):  # type: ignore[union-attr]
                continue

            valid = False
            pair = {cluster.name, peer.name}  # type: ignore[union-attr]
            if pair in found_pairs:
                continue
            found_pairs.append(pair)
            logging.error(
                f"found internal to public vpc peering: {cluster.name} <-> {peer.name}"  # type: ignore[union-attr]
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
            if peer.internal or (peer.spec and peer.spec.private):  # type: ignore[union-attr]
                continue

            valid = False
            pair = {cluster.name, peer.name}  # type: ignore[union-attr]
            if pair in found_pairs:
                continue
            found_pairs.append(pair)
            logging.error(
                f"found public to public vpc peering: {cluster.name} <-> {peer.name}"  # type: ignore[union-attr]
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
