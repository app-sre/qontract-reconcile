import ipaddress
import logging
import sys
from typing import (
    Union,
    cast,
)

from reconcile.gql_definitions.vpc_peerings_validator import vpc_peerings_validator
from reconcile.gql_definitions.vpc_peerings_validator.vpc_peerings_validator import (
    ClusterPeeringConnectionClusterAccepterV1,
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterV1,
    VpcPeeringsValidatorQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql

QONTRACT_INTEGRATION = "vpc-peerings-validator"


def validate_no_cidr_overlap(
    query_data: VpcPeeringsValidatorQueryData,
) -> bool:
    valid = True
    clusters: list[ClusterV1] = query_data.clusters or []

    cidr_block_entries = {}
    for cluster in clusters:
        if cluster.peering:
            for peering in cluster.peering.connections:
                if peering.provider == "account-vpc":
                    cidr_block = str(peering.vpc.cidr_block)  # type: ignore[union-attr]
                    cidr_block_entries[peering.vpc.name] = cidr_block  # type: ignore[union-attr]

        overlaps = find_cidr_duplicates_and_overlap(cidr_block_entries)
        if overlaps:
            return False
    return True


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
