import logging
import sys
from typing import Union, cast

from reconcile.gql_queries.vpc_peerings_validator import vpc_peerings_validator
from reconcile.gql_queries.vpc_peerings_validator.vpc_peerings_validator import (
    ClusterPeeringConnectionClusterAccepterV1,
    ClusterPeeringConnectionClusterRequesterV1,
    VpcPeeringsValidatorQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql


QONTRACT_INTEGRATION = "vpc-peerings-validator"


def validate_no_internal_to_public_peerings(
    query_data: VpcPeeringsValidatorQueryData,
) -> bool:
    """Iterate over VPC peerings of internal clusters and validate the peer is not public."""
    valid = True
    found_pairs: list[set[str]] = []
    for cluster in query_data.clusters or []:
        if not cluster.internal or not cluster.peering:
            continue
        for connection in cluster.peering.connections or []:
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
    for cluster in query_data.clusters or []:
        if (
            cluster.internal
            or (cluster.spec and cluster.spec.private)
            or not cluster.peering
        ):
            continue
        for connection in cluster.peering.connections or []:
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
    gqlapi = gql.get_api()
    clusters = gqlapi.query(vpc_peerings_validator.QUERY)
    query_data: VpcPeeringsValidatorQueryData = VpcPeeringsValidatorQueryData(
        **clusters
    )

    valid = True
    if not validate_no_internal_to_public_peerings(query_data):
        valid = False
    if not validate_no_public_to_public_peerings(query_data):
        valid = False

    if not valid:
        sys.exit(ExitCodes.ERROR)
