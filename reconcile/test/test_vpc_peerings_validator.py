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


@pytest.fixture
def query_data_vpc_cidr_duplicate() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="clustertest",
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


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
                            vpc=AWSVPCV1(cidr_block="192.168.1.0/24", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_vpc_cidr_pass_diff_clusters() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="clustertest1",
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                spec=ClusterSpecV1(private=False),
                internal=False,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
            ClusterV1(
                name="clustertest2",
                network=ClusterNetworkV1(vpc="10.20.0.0/20"),
                spec=ClusterSpecV1(private=False),
                internal=False,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc2"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_vpc_cidr_pass_same_cluster() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="clustertest",
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_vpc_cidr_pass_cluster_same_vpc() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="clustertest",
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
            ClusterV1(
                name="clustertest2",
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_vpc_cidr_pass_cluster_overlap_vpc() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="clustertest",
                network=ClusterNetworkV1(vpc="192.168.0.0/16"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
            ClusterV1(
                name="clustertest2",
                network=ClusterNetworkV1(vpc="192.168.1.0/24"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_vpc_cidr_pass_cluster_diff_vpc() -> VpcPeeringsValidatorQueryData:
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
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
            ClusterV1(
                name="clustertest2",
                network=ClusterNetworkV1(vpc="192.168.1.0/24"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


@pytest.fixture
def query_data_vpc_cidr_same_accepter_vpc() -> VpcPeeringsValidatorQueryData:
    return VpcPeeringsValidatorQueryData(
        clusters=[
            ClusterV1(
                name="clustertest",
                network=ClusterNetworkV1(vpc="10.20.0.0/20"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionClusterAccepterV1(
                            provider="cluster-vpc-accepter",
                            cluster=VpcPeeringsValidatorPeeredCluster(
                                name="clustertest2",
                                network=ClusterNetworkV1(vpc="10.20.0.0/20"),
                                spec=ClusterSpecV1(private=True),
                                internal=True,
                            ),
                        ),
                    ]
                ),
            ),
            ClusterV1(
                name="clustertest2",
                network=ClusterNetworkV1(vpc="10.20.0.0/20"),
                spec=ClusterSpecV1(private=True),
                internal=True,
                peering=ClusterPeeringV1(
                    connections=[
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="10.20.0.0/20", name="vpc1"),
                        ),
                        ClusterPeeringConnectionAccountV1(
                            provider="account-vpc",
                            vpc=AWSVPCV1(cidr_block="192.168.0.0/16", name="vpc2"),
                        ),
                    ]
                ),
            ),
        ]
    )


def test_query_cidr_validator_duplicate(
    query_data_vpc_cidr_duplicate: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_duplicate) is False


def test_query_cidr_validator_overlaps(
    query_data_vpc_cidr_overlap: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_overlap) is False


def test_query_cidr_validator_diff_clusters(
    query_data_vpc_cidr_pass_diff_clusters: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_pass_diff_clusters) is True


def test_query_cidr_validator_same_clusters(
    query_data_vpc_cidr_pass_same_cluster: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_pass_same_cluster) is True


def test_query_cidr_validator_cluster_same_vpc(
    query_data_vpc_cidr_pass_cluster_same_vpc: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_pass_cluster_same_vpc) is False


def test_query_cidr_validator_cluster_vpc_overlaps(
    query_data_vpc_cidr_pass_cluster_overlap_vpc: VpcPeeringsValidatorQueryData,
):
    assert (
        validate_no_cidr_overlap(query_data_vpc_cidr_pass_cluster_overlap_vpc) is False
    )


def test_query_cidr_validator_cluster_vpc_diff(
    query_data_vpc_cidr_pass_cluster_diff_vpc: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_pass_cluster_diff_vpc) is True


def test_query_data_vpc_cidr_same_accepter_vpc(
    query_data_vpc_cidr_same_accepter_vpc: VpcPeeringsValidatorQueryData,
):
    assert validate_no_cidr_overlap(query_data_vpc_cidr_same_accepter_vpc) is False
