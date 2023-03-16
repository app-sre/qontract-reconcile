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
        logging.debug("hello")
        if cluster.peering:
            for peering in cluster.peering.connections:
                if peering.provider == "account-vpc":
                    cidr_block = str(peering.vpc.cidr_block)  # type: ignore[union-attr]
                    # some IPs are for VPCs like ci.int so we'll need to block it from the logic
                    if cidr_block not in (
                        "10.29.88.0/22",
                        "172.32.0.0/16",
                        "172.31.0.0/16",
                        "192.168.0.0/20",
                    ):
                        cidr_block_entries[cluster.name] = cidr_block
                    else:
                        continue

    duplicates, overlaps = find_cidr_duplicates_and_overlap(cidr_block_entries)

    if duplicates:
        valid = False
        return valid
    if overlaps:
        valid = False
        return valid
    return valid


def find_cidr_duplicates_and_overlap(input_dict):
    values = list(input_dict.values())
    duplicates = {
        key: value for key, value in input_dict.items() if values.count(value) > 1
    }

    network_list = [ipaddress.ip_network(value) for value in values]
    overlaps = {}  # type: ignore[var-annotated]

    for i in range(len(network_list)):
        for j in range(i + 1, len(network_list)):
            if network_list[i].overlaps(network_list[j]):
                network1 = next(
                    key
                    for key, val in input_dict.items()
                    if val == str(network_list[i])
                )
                network2 = next(
                    key
                    for key, val in input_dict.items()
                    if val == str(network_list[j])
                )

                if network1 in overlaps:
                    overlaps[network1].append(network2)

    return duplicates, overlaps


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
