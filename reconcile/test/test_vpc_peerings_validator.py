import pytest

from reconcile.gql_definitions.vpc_peerings_validator.vpc_peerings_validator import (
    AWSVPCV1,
    ClusterNetworkV1,
    ClusterPeeringConnectionAccountV1,
    ClusterPeeringConnectionClusterAccepterV1,
    ClusterPeeringV1,
    ClusterSpecV1,
    ClusterV1,
    VpcPeeringsValidatorQueryData,
)
from reconcile.gql_definitions.vpc_peerings_validator.vpc_peerings_validator_peered_cluster_fragment import (
    ClusterSpecV1 as PeeredClusterSpec,
)
from reconcile.gql_definitions.vpc_peerings_validator.vpc_peerings_validator_peered_cluster_fragment import (
    VpcPeeringsValidatorPeeredCluster,
)
from reconcile.vpc_peerings_validator import (
    find_cidr_overlap,
    validate_no_cidr_overlap,
    validate_no_internal_to_public_peerings,
    validate_no_public_to_public_peerings,
)


@pytest.fixture
def query_data_i2p() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="cluster1",
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionClusterAccepterV1(
                            provider="cluster-vpc-accepter",
                            cluster=VpcPeeringsValidatorPeeredCluster(
                                name="cluster2",
                                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                                spec=PeeredClusterSpec(private=False),
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
    query_data_i2p.clusters[0].peering.connections[0].cluster.internal = True  # type: ignore[union-attr]
    assert validate_no_internal_to_public_peerings(query_data_i2p) is True


@pytest.fixture
def query_data_p2p() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="cluster1",
                spec=ClusterSpecV1(private=False),
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                internal=False,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionClusterAccepterV1(
                            provider="cluster-vpc-accepter",
                            cluster=VpcPeeringsValidatorPeeredCluster(
                                name="cluster2",
                                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                                spec=PeeredClusterSpec(private=False),
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


def test_validate_validate_cidr_overlap():
    test_list = [
        {
            "provider": "cluster-self-vpc",
            "vpc_name": "cluster-name",
            "cidr_block": "10.25.0.0/16",
        },
        {
            "provider": "account-vpc",
            "vpc_name": "vpc-name-1",
            "cidr_block": "10.18.0.0/18",
        },
        {
            "provider": "account-vpc",
            "vpc_name": "vpc-name-2",
            "cidr_block": "10.18.0.0/18",
        },
    ]
    cluster_name = "cluster-name"
    assert find_cidr_overlap(cluster_name, test_list) is True


def test_validate_validate_no_cidr_overlap():
    test_list = [
        {
            "provider": "cluster-self-vpc",
            "vpc_name": "cluster-name",
            "cidr_block": "10.25.0.0/16",
        },
        {
            "provider": "account-vpc",
            "vpc_name": "vpc-name-1",
            "cidr_block": "10.18.0.0/18",
        },
        {
            "provider": "account-vpc",
            "vpc_name": "vpc-name-2",
            "cidr_block": "10.19.0.0/18",
        },
    ]
    cluster_name = "cluster-name"
    assert find_cidr_overlap(cluster_name, test_list) is False


@pytest.fixture
def query_data_vpc_cidr_overlap() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="clustertest",
                network=ClusterNetworkV1(vpc="10.20.0.0/20"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(
                                cidr_block="192.168.1.0/24",
                                name="vpc1",
                            ),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(
                                cidr_block="192.168.1.0/24",
                                name="vpc2",
                            ),
                        ),
                    ]
                ),
            ),
        ]
    )


def test_create_dict_for_validate_no_cidr_overlap(
    query_data_vpc_cidr_overlap: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_overlap) is False
