import pytest

from reconcile.gql_definitions.vpc_peerings_validator.vpc_peerings_validator import (
    ClusterPeeringConnectionClusterAccepterV1,
    ClusterPeeringConnectionClusterAccepterV1_ClusterV1,
    ClusterPeeringConnectionClusterAccepterV1_ClusterV1_ClusterSpecV1,
    ClusterPeeringV1,
    ClusterSpecV1,
    ClusterV1,
    VpcPeeringsValidatorQueryData,
)
from reconcile.vpc_peerings_validator import (
    validate_no_internal_to_public_peerings,
    validate_no_public_to_public_peerings,
)


@pytest.fixture
def query_data_i2p() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="cluster1",
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionClusterAccepterV1(
                            provider="cluster-vpc-accepter",
                            cluster=ClusterPeeringConnectionClusterAccepterV1_ClusterV1(
                                name="cluster2",
                                spec=ClusterPeeringConnectionClusterAccepterV1_ClusterV1_ClusterSpecV1(
                                    private=False
                                ),
                                internal=False,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


def test_validate_no_internal_to_public_peerings_invalid(
    query_data_i2p: VpcPeeringsValidatorQueryData,
):
    assert validate_no_internal_to_public_peerings(query_data_i2p) is False


def test_validate_no_internal_to_public_peerings_valid_private(
    query_data_i2p: VpcPeeringsValidatorQueryData,
):
    query_data_i2p.clusters[0].peering.connections[0].cluster.spec.private = True  # type: ignore[index,union-attr]
    assert validate_no_internal_to_public_peerings(query_data_i2p) is True


def test_validate_no_internal_to_public_peerings_valid_internal(
    query_data_i2p: VpcPeeringsValidatorQueryData,
):
    assert query_data_i2p.clusters is not None
    query_data_i2p.clusters[0].peering.connections[0].cluster.internal = True  # type: ignore[index,union-attr]
    assert validate_no_internal_to_public_peerings(query_data_i2p) is True


@pytest.fixture
def query_data_p2p() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="cluster1",
                spec=ClusterSpecV1(private=False),
                internal=False,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionClusterAccepterV1(
                            provider="cluster-vpc-accepter",
                            cluster=ClusterPeeringConnectionClusterAccepterV1_ClusterV1(
                                name="cluster2",
                                spec=ClusterPeeringConnectionClusterAccepterV1_ClusterV1_ClusterSpecV1(
                                    private=False
                                ),
                                internal=False,
                            ),
                        ),
                    ],
                ),
            ),
        ],
    )


def test_validate_no_public_to_public_peerings_invalid(
    query_data_p2p: VpcPeeringsValidatorQueryData,
):
    assert validate_no_public_to_public_peerings(query_data_p2p) is False


def test_validate_no_public_to_public_peerings_valid(
    query_data_p2p: VpcPeeringsValidatorQueryData,
):
    query_data_p2p.clusters[0].peering.connections[0].cluster.spec.private = True  # type: ignore[index,union-attr]
    assert validate_no_public_to_public_peerings(query_data_p2p) is True
