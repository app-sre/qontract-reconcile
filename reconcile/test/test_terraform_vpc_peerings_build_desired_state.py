from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

import reconcile.terraform_vpc_peerings as sut
from reconcile.test.test_terraform_vpc_peerings import (
    MockAWSAPI,
    MockOCM,
    build_accepter_connection,
    build_cluster,
    build_requester_connection,
)
from reconcile.utils import (
    aws_api,
    ocm,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_c2c_all_clusters() -> None:
    """
    happy path
    """

    accepter_cluster = build_cluster(
        name="accepter_cluster",
        vpc="accepter_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_accepter_connection(name="peername", cluster="requester_cluster")
        ],
    )
    requester_cluster = build_cluster(
        name="requester_cluster",
        vpc="requester_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_requester_connection(name="peername", peer_cluster=accepter_cluster)
        ],
    )

    ocm_map = {
        "requester_cluster": MockOCM()
        .register("requester_cluster", "acc", "terraform", "r")
        .register("accepter_cluster", "acc", "terraform", "a")
    }

    awsapi = (
        MockAWSAPI()
        .register(
            vpc="accepter_vpc",
            vpc_id="accepter_vpc_id",
            route_tables=["accepter_rt_id"],
        )
        .register(
            vpc="requester_vpc",
            vpc_id="requester_vpc_id",
            route_tables=["requester_rt_id"],
        )
    )

    expected = [
        {
            "connection_provider": "cluster-vpc-requester",
            "connection_name": "peername",
            "infra_account_name": "acc",
            "requester": {
                "cidr_block": "requester_vpc",
                "region": "region",
                "vpc_id": "requester_vpc_id",
                "route_table_ids": ["requester_rt_id"],
                "api_security_group_id": None,
                "account": {
                    "name": "acc",
                    "uid": "acc",
                    "terraformUsername": "terraform",
                    "automationToken": {},
                    "assume_role": "arn::::r",
                    "assume_region": "region",
                    "assume_cidr": "requester_vpc",
                },
                "peer_owner_id": "a",
            },
            "accepter": {
                "cidr_block": "accepter_vpc",
                "region": "region",
                "vpc_id": "accepter_vpc_id",
                "route_table_ids": ["accepter_rt_id"],
                "api_security_group_id": None,
                "account": {
                    "name": "acc",
                    "uid": "acc",
                    "terraformUsername": "terraform",
                    "automationToken": {},
                    "assume_role": "arn::::a",
                    "assume_region": "region",
                    "assume_cidr": "accepter_vpc",
                },
            },
            "deleted": False,
        }
    ]

    # no account filter
    result, error = sut.build_desired_state_all_clusters(
        [requester_cluster],
        ocm_map,  # type: ignore
        awsapi,  # type: ignore
        account_filter=None,
    )
    assert result == expected
    assert not error

    # correct account filter
    result, error = sut.build_desired_state_all_clusters(
        [requester_cluster],
        ocm_map,  # type: ignore
        awsapi,  # type: ignore
        account_filter="acc",
    )
    assert result == expected
    assert not error

    # wrong account filter
    result, error = sut.build_desired_state_all_clusters(
        [requester_cluster],
        ocm_map,  # type: ignore
        awsapi,  # type: ignore
        account_filter="another_account",
    )
    assert not result
    assert not error


def test_c2c_one_cluster_failing_recoverable(mocker: MockerFixture) -> None:
    """
    in this scenario, the handling of a single cluster fails with known
    exceptions
    """
    build_desired_state_single_cluster = mocker.patch.object(
        sut, "build_desired_state_single_cluster"
    )
    build_desired_state_single_cluster.side_effect = sut.BadTerraformPeeringStateError(
        "something bad"
    )

    result, error = sut.build_desired_state_all_clusters(
        [{"name": "cluster"}],
        None,
        None,  # type: ignore
        account_filter=None,
    )

    assert not result
    assert error


def test_c2c_one_cluster_failing_weird(mocker: MockerFixture) -> None:
    """
    in this scenario, the handling of a single cluster fails with unexpected
    exceptions
    """
    build_desired_state_single_cluster = mocker.patch.object(
        sut, "build_desired_state_single_cluster"
    )
    something_unexpected = "nobody expects the spanish inquisition"
    build_desired_state_single_cluster.side_effect = ValueError(something_unexpected)

    with pytest.raises(ValueError) as ex:
        sut.build_desired_state_all_clusters(
            [{"name": "cluster"}],
            None,
            None,  # type: ignore
            account_filter=None,
        )

    assert str(ex.value) == something_unexpected


@pytest.mark.parametrize(
    "accepter_hcp, accepter_private, requester_hcp, requester_private, expected_accepter_security_group, expected_requester_security_group",
    [
        (True, True, True, True, "sg-accepter", "sg-requester"),
        (True, False, True, True, None, "sg-requester"),
        (False, True, True, True, None, "sg-requester"),
        (False, False, True, True, None, "sg-requester"),
        (True, True, True, False, "sg-accepter", None),
        (True, True, False, True, "sg-accepter", None),
        (True, True, False, False, "sg-accepter", None),
    ],
)
def test_c2c_hcp(
    accepter_hcp: bool,
    accepter_private: bool,
    requester_hcp: bool,
    requester_private: bool,
    expected_accepter_security_group: str | None,
    expected_requester_security_group: str | None,
) -> None:
    accepter_cluster = build_cluster(
        name="accepter_cluster",
        vpc="accepter_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_accepter_connection(name="peername", cluster="requester_cluster")
        ],
        hcp=accepter_hcp,
        private=accepter_private,
    )
    requester_cluster = build_cluster(
        name="requester_cluster",
        vpc="requester_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_requester_connection(name="peername", peer_cluster=accepter_cluster)
        ],
        hcp=requester_hcp,
        private=requester_private,
    )
    ocm = (
        MockOCM()
        .register("requester_cluster", "acc", "terraform", "r")
        .register("accepter_cluster", "acc", "terraform", "a")
    )

    awsapi = (
        MockAWSAPI()
        .register(
            vpc="accepter_vpc",
            vpc_id="accepter_vpc_id",
            route_tables=["accepter_rt_id"],
            vpce_sg=expected_accepter_security_group,
        )
        .register(
            vpc="requester_vpc",
            vpc_id="requester_vpc_id",
            route_tables=["requester_rt_id"],
            vpce_sg=expected_requester_security_group,
        )
    )

    expected = [
        {
            "connection_provider": "cluster-vpc-requester",
            "connection_name": "peername",
            "infra_account_name": "acc",
            "requester": {
                "cidr_block": "requester_vpc",
                "region": "region",
                "vpc_id": "requester_vpc_id",
                "route_table_ids": ["requester_rt_id"],
                "api_security_group_id": expected_requester_security_group,
                "account": {
                    "name": "acc",
                    "uid": "acc",
                    "terraformUsername": "terraform",
                    "automationToken": {},
                    "assume_role": "arn::::r",
                    "assume_region": "region",
                    "assume_cidr": "requester_vpc",
                },
                "peer_owner_id": "a",
            },
            "accepter": {
                "cidr_block": "accepter_vpc",
                "region": "region",
                "vpc_id": "accepter_vpc_id",
                "route_table_ids": ["accepter_rt_id"],
                "api_security_group_id": expected_accepter_security_group,
                "account": {
                    "name": "acc",
                    "uid": "acc",
                    "terraformUsername": "terraform",
                    "automationToken": {},
                    "assume_role": "arn::::a",
                    "assume_region": "region",
                    "assume_cidr": "accepter_vpc",
                },
            },
            "deleted": False,
        }
    ]

    # no account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster,
        ocm,  # type: ignore
        awsapi,  # type: ignore
        account_filter=None,
    )
    assert result == expected

    # correct account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster,
        ocm,  # type: ignore
        awsapi,  # type: ignore
        account_filter="acc",
    )
    assert result == expected

    # correct account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster,
        ocm,  # type: ignore
        awsapi,  # type: ignore
        account_filter="another_account",
    )
    assert not result


def test_c2c_base() -> None:
    """
    happy path
    """
    accepter_cluster = build_cluster(
        name="accepter_cluster",
        vpc="accepter_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_accepter_connection(name="peername", cluster="requester_cluster")
        ],
    )
    requester_cluster = build_cluster(
        name="requester_cluster",
        vpc="requester_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_requester_connection(name="peername", peer_cluster=accepter_cluster)
        ],
    )
    ocm = (
        MockOCM()
        .register("requester_cluster", "acc", "terraform", "r")
        .register("accepter_cluster", "acc", "terraform", "a")
    )

    awsapi = (
        MockAWSAPI()
        .register(
            vpc="accepter_vpc",
            vpc_id="accepter_vpc_id",
            route_tables=["accepter_rt_id"],
        )
        .register(
            vpc="requester_vpc",
            vpc_id="requester_vpc_id",
            route_tables=["requester_rt_id"],
        )
    )

    expected = [
        {
            "connection_provider": "cluster-vpc-requester",
            "connection_name": "peername",
            "infra_account_name": "acc",
            "requester": {
                "cidr_block": "requester_vpc",
                "region": "region",
                "vpc_id": "requester_vpc_id",
                "route_table_ids": ["requester_rt_id"],
                "api_security_group_id": None,
                "account": {
                    "name": "acc",
                    "uid": "acc",
                    "terraformUsername": "terraform",
                    "automationToken": {},
                    "assume_role": "arn::::r",
                    "assume_region": "region",
                    "assume_cidr": "requester_vpc",
                },
                "peer_owner_id": "a",
            },
            "accepter": {
                "cidr_block": "accepter_vpc",
                "region": "region",
                "vpc_id": "accepter_vpc_id",
                "route_table_ids": ["accepter_rt_id"],
                "api_security_group_id": None,
                "account": {
                    "name": "acc",
                    "uid": "acc",
                    "terraformUsername": "terraform",
                    "automationToken": {},
                    "assume_role": "arn::::a",
                    "assume_region": "region",
                    "assume_cidr": "accepter_vpc",
                },
            },
            "deleted": False,
        }
    ]

    # no account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster,
        ocm,  # type: ignore
        awsapi,  # type: ignore
        account_filter=None,
    )
    assert result == expected

    # correct account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster,
        ocm,  # type: ignore
        awsapi,  # type: ignore
        account_filter="acc",
    )
    assert result == expected

    # correct account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster,
        ocm,  # type: ignore
        awsapi,  # type: ignore
        account_filter="another_account",
    )
    assert not result


def test_c2c_no_peerings() -> None:
    """
    in this scenario, the requester cluster has no peerings defines,
    which results in an empty desired state
    """
    requester_cluster = build_cluster(
        name="requester_cluster",
        vpc="requester_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[],
    )
    result = sut.build_desired_state_single_cluster(
        requester_cluster,
        MockOCM(),  # type: ignore
        MockAWSAPI(),  # type: ignore
        account_filter=None,
    )
    assert not result


def test_c2c_no_matches() -> None:
    """
    in this scenario, the accepter cluster has no cluster-vpc-accepter
    connection that references back to the requester cluster
    """
    accepter_cluster = build_cluster(
        name="accepter_cluster",
        vpc="accepter_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_accepter_connection(name="peername", cluster="not_a_matching_cluster")
        ],
    )
    requester_cluster = build_cluster(
        name="requester_cluster",
        vpc="requester_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_requester_connection(name="peername", peer_cluster=accepter_cluster)
        ],
    )

    with pytest.raises(sut.BadTerraformPeeringStateError) as ex:
        sut.build_desired_state_single_cluster(
            requester_cluster,
            MockOCM(),  # type: ignore
            MockAWSAPI(),  # type: ignore
            account_filter=None,
        )
    assert str(ex.value).startswith("[no_matching_peering]")


def test_c2c_no_vpc_in_aws() -> None:
    """
    in this scenario, there are no VPCs found in AWS
    """
    accepter_cluster = build_cluster(
        name="accepter_cluster",
        vpc="accepter_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_accepter_connection(name="peername", cluster="requester_cluster")
        ],
    )
    requester_cluster = build_cluster(
        name="requester_cluster",
        vpc="requester_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_requester_connection(name="peername", peer_cluster=accepter_cluster)
        ],
    )

    ocm = (
        MockOCM()
        .register("requester_cluster", "acc", "terraform", "r")
        .register("accepter_cluster", "acc", "terraform", "a")
    )

    awsapi = MockAWSAPI()

    desired_state = sut.build_desired_state_single_cluster(
        requester_cluster,
        ocm,  # type: ignore
        awsapi,  # type: ignore
        account_filter=None,
    )
    assert desired_state == []


def test_c2c_no_peer_account() -> None:
    """
    in this scenario, the accepters connection and the accepters cluster
    have no aws infrastructura account available to set up the peering″
    """
    accepter_cluster = build_cluster(
        # no network_mgmt_accounts here
        name="accepter_cluster",
        vpc="accepter_vpc",
        peering_connections=[
            build_accepter_connection(
                # no network_mgmt_accounts here
                name="peername",
                cluster="requester_cluster",
            )
        ],
    )
    requester_cluster = build_cluster(
        name="requester_cluster",
        vpc="requester_vpc",
        network_mgmt_accounts=["acc"],
        peering_connections=[
            build_requester_connection(name="peername", peer_cluster=accepter_cluster)
        ],
    )

    ocm = MockOCM()
    awsapi = MockAWSAPI()

    with pytest.raises(sut.BadTerraformPeeringStateError) as ex:
        sut.build_desired_state_single_cluster(
            requester_cluster,
            ocm,  # type: ignore
            awsapi,  # type: ignore
            account_filter=None,
        )
    assert str(ex.value).startswith("[no_account_available]")


@dataclass
class VpcMeshState:
    clusters: list[dict[str, Any]]
    peer_account: dict[str, Any]
    ocm_mock: MagicMock
    ocm_map: dict[str, MagicMock]
    awsapi: MagicMock
    vpc_mesh_single_cluster: MagicMock
    account_vpcs: list[dict[str, Any]]


@pytest.fixture
def vpc_mesh_state(mocker: MockerFixture) -> VpcMeshState:
    peer_account: dict[str, Any] = {
        "name": "peer_account",
        "uid": "peeruid",
        "terraformUsername": "peerterraformusename",
        "automationtoken": "peeranautomationtoken",
        "assume_role": "a:peer:role:indeed:it:is",
        "assume_region": "mars-hellas-1",
        "assume_cidr": "172.25.0.0/12",
    }
    peer_cluster: dict[str, Any] = {
        "name": "apeerclustername",
        "spec": {"region": "mars-olympus-2"},
        "network": {
            "vpc": "172.17.0.0/12",
            "service": "10.1.0.0/8",
            "pod": "192.168.1.0/16",
        },
        "peering": {
            "connections": [
                {
                    "provider": "cluster-vpc-requester",
                    "name": "peername",
                    "vpc": {"$ref": "/aws/account/vpcs/mars-plain-1"},
                    "manageRoutes": True,
                    "tags": '["tag1"]',
                },
            ]
        },
    }
    clusters: list[dict[str, Any]] = [
        {
            "name": "clustername",
            "spec": {"region": "mars-plain-1"},
            "network": {
                "vpc": "172.16.0.0/12",
                "service": "10.0.0.0/8",
                "pod": "192.168.0.0/16",
            },
            "peering": {
                "connections": [
                    {
                        "provider": "account-vpc-mesh",
                        "name": "peername",
                        "vpc": {"$ref": "/aws/account/vpcs/mars-plain-1"},
                        "manageRoutes": True,
                        "tags": '["tag1"]',
                        "cluster": peer_cluster,
                        "account": peer_account,
                    },
                ]
            },
        }
    ]

    ocm_mock = MagicMock(spec=ocm.OCM)
    ocm_mock.get_aws_infrastructure_access_terraform_assume_role.side_effect = (
        lambda cluster, uid, tfuser: peer_account["assume_role"]
    )
    ocm_map = cast("ocm.OCMMap", {"clustername": ocm_mock})

    awsapi = MagicMock(spec=aws_api.AWSApi)

    vpc_mesh_single_cluster = mocker.patch.object(
        sut, "build_desired_state_vpc_mesh_single_cluster"
    )

    account_vpcs: list[dict[str, Any]] = [
        {
            "vpc_id": "vpc1",
            "region": "moon-dark-1",
            "cidr_block": "192.168.3.0/24",
            "route_table_ids": ["vpc1_route_table"],
        },
        {
            "vpc_id": "vpc2",
            "region": "mars-utopia-2",
            "cidr_block": "192.168.4.0/24",
            "route_table_ids": ["vpc2_route_table"],
        },
    ]

    return VpcMeshState(
        clusters=clusters,
        peer_account=peer_account,
        ocm_mock=ocm_mock,
        ocm_map=ocm_map,
        awsapi=awsapi,
        vpc_mesh_single_cluster=vpc_mesh_single_cluster,
        account_vpcs=account_vpcs,
    )


def test_vpc_mesh_all_fine(vpc_mesh_state: VpcMeshState) -> None:
    expected = [
        {
            "connection_provider": "account-vpc-mesh",
            "connection_name": "peername_peer_account-vpc1",
            "requester": {
                "vpc_id": "vpc_id",
                "route_table_ids": ["route_table_id"],
                "account": vpc_mesh_state.peer_account,
                "region": "mars-plain-1",
                "cidr_block": "172.16.0.0/12",
            },
            "accepter": {
                "vpc_id": "vpc1",
                "region": "moon-dark-1",
                "cidr_block": "192.168.3.0/24",
                "route_table_ids": ["vpc1_route_table"],
                "account": vpc_mesh_state.peer_account,
            },
            "deleted": False,
        },
        {
            "connection_provider": "account-vpc-mesh",
            "connection_name": "peername_peer_account-vpc2",
            "requester": {
                "vpc_id": "vpc_id",
                "route_table_ids": ["route_table_id"],
                "account": vpc_mesh_state.peer_account,
                "region": "mars-plain-1",
                "cidr_block": "172.16.0.0/12",
            },
            "accepter": {
                "vpc_id": "vpc2",
                "region": "mars-utopia-2",
                "cidr_block": "192.168.4.0/24",
                "route_table_ids": ["vpc2_route_table"],
                "account": vpc_mesh_state.peer_account,
            },
            "deleted": False,
        },
    ]
    vpc_mesh_state.vpc_mesh_single_cluster.return_value = expected

    rs = sut.build_desired_state_vpc_mesh(
        vpc_mesh_state.clusters,
        vpc_mesh_state.ocm_map,
        vpc_mesh_state.awsapi,
        None,
    )
    assert rs == (expected, False)


def test_vpc_mesh_cluster_raises(vpc_mesh_state: VpcMeshState) -> None:
    vpc_mesh_state.vpc_mesh_single_cluster.side_effect = (
        sut.BadTerraformPeeringStateError("This is wrong")
    )
    rs = sut.build_desired_state_vpc_mesh(
        vpc_mesh_state.clusters,
        vpc_mesh_state.ocm_map,
        vpc_mesh_state.awsapi,
        None,
    )
    assert rs == ([], True)


def test_vpc_mesh_cluster_raises_unexpected(vpc_mesh_state: VpcMeshState) -> None:
    vpc_mesh_state.vpc_mesh_single_cluster.side_effect = ValueError("Nope")
    with pytest.raises(ValueError):
        sut.build_desired_state_vpc_mesh(
            vpc_mesh_state.clusters,
            vpc_mesh_state.ocm_map,
            vpc_mesh_state.awsapi,
            None,
        )


@dataclass
class VpcMeshSingleState:
    cluster: dict[str, Any]
    peer_account: dict[str, Any]
    ocm_mock: MagicMock
    awsapi: MagicMock
    find_matching_peering: MagicMock
    account_vpcs: list[dict[str, Any]]


@pytest.fixture
def vpc_mesh_single_state(mocker: MockerFixture) -> VpcMeshSingleState:
    peer_account: dict[str, Any] = {
        "name": "peer_account",
        "uid": "peeruid",
        "terraformUsername": "peerterraformusename",
        "automationtoken": "peeranautomationtoken",
        "assume_role": "a:peer:role:indeed:it:is",
        "assume_region": "mars-hellas-1",
        "assume_cidr": "172.25.0.0/12",
    }
    peer_cluster: dict[str, Any] = {
        "name": "apeerclustername",
        "spec": {"region": "mars-olympus-2"},
        "network": {
            "vpc": "172.17.0.0/12",
            "service": "10.1.0.0/8",
            "pod": "192.168.1.0/16",
        },
        "peering": {
            "connections": [
                {
                    "provider": "cluster-vpc-requester",
                    "name": "peername",
                    "vpc": {"$ref": "/aws/account/vpcs/mars-plain-1"},
                    "manageRoutes": True,
                    "tags": '["tag1"]',
                },
            ]
        },
    }
    cluster: dict[str, Any] = {
        "name": "clustername",
        "spec": {"region": "mars-plain-1"},
        "network": {
            "vpc": "172.16.0.0/12",
            "service": "10.0.0.0/8",
            "pod": "192.168.0.0/16",
        },
        "peering": {
            "connections": [
                {
                    "provider": "account-vpc-mesh",
                    "name": "peername",
                    "vpc": {"$ref": "/aws/account/vpcs/mars-plain-1"},
                    "manageRoutes": True,
                    "tags": '["tag1"]',
                    "cluster": peer_cluster,
                    "account": peer_account,
                },
            ]
        },
    }

    ocm_mock = MagicMock(spec=ocm.OCM)
    ocm_mock.get_aws_infrastructure_access_terraform_assume_role.side_effect = (
        lambda cluster_arg, tf_account_id, tf_user: peer_account["assume_role"]
    )

    awsapi = MagicMock(spec=aws_api.AWSApi)
    find_matching_peering = mocker.patch.object(sut, "find_matching_peering")

    account_vpcs: list[dict[str, Any]] = [
        {
            "vpc_id": "vpc1",
            "region": "moon-dark-1",
            "cidr_block": "192.168.3.0/24",
            "route_table_ids": ["vpc1_route_table"],
        },
        {
            "vpc_id": "vpc2",
            "region": "mars-utopia-2",
            "cidr_block": "192.168.4.0/24",
            "route_table_ids": ["vpc2_route_table"],
        },
    ]

    return VpcMeshSingleState(
        cluster=cluster,
        peer_account=peer_account,
        ocm_mock=ocm_mock,
        awsapi=awsapi,
        find_matching_peering=find_matching_peering,
        account_vpcs=account_vpcs,
    )


def test_vpc_mesh_single_one_cluster(vpc_mesh_single_state: VpcMeshSingleState) -> None:
    vpc_mesh_single_state.awsapi.get_cluster_vpc_details.return_value = (
        "vpc_id",
        ["route_table_id"],
        "subnet_id",
        None,
    )
    vpc_mesh_single_state.awsapi.get_vpcs_details.return_value = (
        vpc_mesh_single_state.account_vpcs
    )

    expected = [
        {
            "connection_provider": "account-vpc-mesh",
            "connection_name": "peername_peer_account-vpc1",
            "infra_account_name": vpc_mesh_single_state.peer_account["name"],
            "requester": {
                "vpc_id": "vpc_id",
                "route_table_ids": ["route_table_id"],
                "api_security_group_id": None,
                "account": vpc_mesh_single_state.peer_account,
                "region": "mars-plain-1",
                "cidr_block": "172.16.0.0/12",
            },
            "accepter": {
                "vpc_id": "vpc1",
                "region": "moon-dark-1",
                "cidr_block": "192.168.3.0/24",
                "route_table_ids": ["vpc1_route_table"],
                "account": vpc_mesh_single_state.peer_account,
            },
            "deleted": False,
        },
        {
            "connection_provider": "account-vpc-mesh",
            "connection_name": "peername_peer_account-vpc2",
            "infra_account_name": vpc_mesh_single_state.peer_account["name"],
            "requester": {
                "vpc_id": "vpc_id",
                "route_table_ids": ["route_table_id"],
                "api_security_group_id": None,
                "account": vpc_mesh_single_state.peer_account,
                "region": "mars-plain-1",
                "cidr_block": "172.16.0.0/12",
            },
            "accepter": {
                "vpc_id": "vpc2",
                "region": "mars-utopia-2",
                "cidr_block": "192.168.4.0/24",
                "route_table_ids": ["vpc2_route_table"],
                "account": vpc_mesh_single_state.peer_account,
            },
            "deleted": False,
        },
    ]

    rs = sut.build_desired_state_vpc_mesh_single_cluster(
        vpc_mesh_single_state.cluster,
        vpc_mesh_single_state.ocm_mock,
        vpc_mesh_single_state.awsapi,
        None,
    )
    assert rs == expected
    vpc_mesh_single_state.awsapi.get_cluster_vpc_details.assert_called_once()
    vpc_mesh_single_state.awsapi.get_vpcs_details.assert_called_once()


def test_vpc_mesh_single_one_cluster_private_hcp(
    vpc_mesh_single_state: VpcMeshSingleState,
) -> None:
    vpc_mesh_single_state.cluster["spec"] = {
        "region": "mars-plain-1",
        "hypershift": True,
        "private": True,
    }
    vpc_mesh_single_state.awsapi.get_cluster_vpc_details.return_value = (
        "vpc_id",
        ["route_table_id"],
        "subnet_id",
        "sg-vpce",
    )
    vpc_mesh_single_state.awsapi.get_vpcs_details.return_value = (
        vpc_mesh_single_state.account_vpcs
    )

    expected = [
        {
            "connection_provider": "account-vpc-mesh",
            "connection_name": "peername_peer_account-vpc1",
            "infra_account_name": vpc_mesh_single_state.peer_account["name"],
            "requester": {
                "vpc_id": "vpc_id",
                "route_table_ids": ["route_table_id"],
                "api_security_group_id": "sg-vpce",
                "account": vpc_mesh_single_state.peer_account,
                "region": "mars-plain-1",
                "cidr_block": "172.16.0.0/12",
            },
            "accepter": {
                "vpc_id": "vpc1",
                "region": "moon-dark-1",
                "cidr_block": "192.168.3.0/24",
                "route_table_ids": ["vpc1_route_table"],
                "account": vpc_mesh_single_state.peer_account,
            },
            "deleted": False,
        },
        {
            "connection_provider": "account-vpc-mesh",
            "connection_name": "peername_peer_account-vpc2",
            "infra_account_name": vpc_mesh_single_state.peer_account["name"],
            "requester": {
                "vpc_id": "vpc_id",
                "route_table_ids": ["route_table_id"],
                "api_security_group_id": "sg-vpce",
                "account": vpc_mesh_single_state.peer_account,
                "region": "mars-plain-1",
                "cidr_block": "172.16.0.0/12",
            },
            "accepter": {
                "vpc_id": "vpc2",
                "region": "mars-utopia-2",
                "cidr_block": "192.168.4.0/24",
                "route_table_ids": ["vpc2_route_table"],
                "account": vpc_mesh_single_state.peer_account,
            },
            "deleted": False,
        },
    ]

    rs = sut.build_desired_state_vpc_mesh_single_cluster(
        vpc_mesh_single_state.cluster,
        vpc_mesh_single_state.ocm_mock,
        vpc_mesh_single_state.awsapi,
        None,
    )
    assert rs == expected
    vpc_mesh_single_state.awsapi.get_cluster_vpc_details.assert_called_once()
    vpc_mesh_single_state.awsapi.get_vpcs_details.assert_called_once()


def test_vpc_mesh_single_no_peering_connections(
    vpc_mesh_single_state: VpcMeshSingleState,
) -> None:
    vpc_mesh_single_state.cluster["peering"]["connections"] = []  # type: ignore
    rs = sut.build_desired_state_vpc_mesh_single_cluster(
        vpc_mesh_single_state.cluster,
        vpc_mesh_single_state.ocm_mock,
        vpc_mesh_single_state.awsapi,
        None,
    )
    assert rs == []


def test_vpc_mesh_single_no_peer_vpc_id(
    vpc_mesh_single_state: VpcMeshSingleState,
) -> None:
    vpc_mesh_single_state.awsapi.get_cluster_vpc_details.return_value = (
        None,
        [None],
        None,
        None,
    )

    desired_state = sut.build_desired_state_vpc_mesh_single_cluster(
        vpc_mesh_single_state.cluster,
        vpc_mesh_single_state.ocm_mock,
        vpc_mesh_single_state.awsapi,
        None,
    )
    assert desired_state == []
    vpc_mesh_single_state.awsapi.get_cluster_vpc_details.assert_called_once()


@dataclass
class VpcState:
    clusters: list[dict[str, Any]]
    aws_account: dict[str, Any]
    ocm_mock: MagicMock
    ocm_map: dict[str, MagicMock]
    awsapi: MagicMock
    build_single_cluster: MagicMock


@pytest.fixture
def vpc_state(mocker: MockerFixture) -> VpcState:
    aws_account: dict[str, Any] = {
        "name": "accountname",
        "uid": "anuid",
        "terraformUsername": "aterraformusename",
        "automationtoken": "anautomationtoken",
        "assume_role": "arole:very:useful:indeed:it:is",
        "assume_region": "moon-tranquility-1",
        "assume_cidr": "172.25.0.0/12",
    }
    peer: dict[str, Any] = {
        "vpc": "172.17.0.0/12",
        "service": "10.1.0.0/8",
        "pod": "192.168.1.0/16",
    }
    peer_cluster: dict[str, Any] = {
        "name": "apeerclustername",
        "spec": {"region": "mars-olympus-2"},
        "network": peer,
        "peering": {
            "connections": [
                {
                    "provider": "account-vpc",
                    "name": "peername",
                    "vpc": {"$ref": "/aws/account/vpcs/mars-plain-1"},
                    "manageRoutes": True,
                },
            ]
        },
    }
    clusters: list[dict[str, Any]] = [
        {
            "name": "clustername",
            "spec": {"region": "mars-plain-1"},
            "network": {
                "vpc": "172.16.0.0/12",
                "service": "10.0.0.0/8",
                "pod": "192.168.0.0/16",
            },
            "peering": {
                "connections": [
                    {
                        "provider": "account-vpc",
                        "name": "peername",
                        "vpc": {
                            "$ref": "/aws/account/vpcs/mars-plain-1",
                            "cidr_block": "172.30.0.0/12",
                            "vpc_id": "avpcid",
                            **peer,
                            "region": "mars-olympus-2",
                            "account": aws_account,
                        },
                        "manageRoutes": True,
                        "cluster": peer_cluster,
                    },
                ]
            },
        }
    ]

    ocm_mock = MagicMock(spec=ocm.OCM)
    ocm_map = cast("ocm.OCMMap", {"clustername": ocm_mock})
    awsapi = MagicMock(spec=aws_api.AWSApi)
    build_single_cluster = mocker.patch.object(
        sut, "build_desired_state_vpc_single_cluster"
    )

    return VpcState(
        clusters=clusters,
        aws_account=aws_account,
        ocm_mock=ocm_mock,
        ocm_map=ocm_map,
        awsapi=awsapi,
        build_single_cluster=build_single_cluster,
    )


def test_vpc_all_fine(vpc_state: VpcState) -> None:
    expected = [
        {
            "accepter": {
                "account": {
                    "assume_cidr": "172.16.0.0/12",
                    "assume_region": "mars-plain-1",
                    "assume_role": "this:wonderful:role:hell:yeah",
                    "automationtoken": "anautomationtoken",
                    "name": "accountname",
                    "terraformUsername": "aterraformusename",
                    "uid": "anuid",
                },
                "cidr_block": "172.30.0.0/12",
                "region": "mars-olympus-2",
                "vpc_id": "avpcid",
            },
            "connection_name": "peername",
            "connection_provider": "account-vpc",
            "deleted": False,
            "requester": {
                "account": {
                    "assume_cidr": "172.16.0.0/12",
                    "assume_region": "mars-plain-1",
                    "assume_role": "this:wonderful:role:hell:yeah",
                    "automationtoken": "anautomationtoken",
                    "name": "accountname",
                    "terraformUsername": "aterraformusename",
                    "uid": "anuid",
                },
                "cidr_block": "172.16.0.0/12",
                "region": "mars-plain-1",
                "route_table_ids": ["routetableid"],
                "vpc_id": "vpcid",
            },
        }
    ]
    vpc_state.build_single_cluster.return_value = expected

    rs = sut.build_desired_state_vpc(
        vpc_state.clusters, vpc_state.ocm_map, vpc_state.awsapi, account_filter=None
    )
    assert rs == (expected, False)
    vpc_state.build_single_cluster.assert_called_once()


def test_vpc_cluster_fails(vpc_state: VpcState) -> None:
    vpc_state.build_single_cluster.side_effect = sut.BadTerraformPeeringStateError(
        "I have failed"
    )

    assert sut.build_desired_state_vpc(
        vpc_state.clusters, vpc_state.ocm_map, vpc_state.awsapi, account_filter=None
    ) == ([], True)


def test_vpc_error_persists(vpc_state: VpcState) -> None:
    vpc_state.clusters.append(vpc_state.clusters[0].copy())
    vpc_state.clusters[1]["name"] = "afailingcluster"
    vpc_state.ocm_map["afailingcluster"] = vpc_state.ocm_mock  # type: ignore
    vpc_state.build_single_cluster.side_effect = [
        [{"a dict": "a value"}],
        sut.BadTerraformPeeringStateError("Fail!"),
    ]

    assert sut.build_desired_state_vpc(
        vpc_state.clusters, vpc_state.ocm_map, vpc_state.awsapi, account_filter=None
    ) == ([{"a dict": "a value"}], True)
    assert vpc_state.build_single_cluster.call_count == 2


def test_vpc_other_exceptions_raise(vpc_state: VpcState) -> None:
    vpc_state.clusters.append(vpc_state.clusters[0].copy())
    vpc_state.clusters[1]["name"] = "afailingcluster"
    vpc_state.ocm_map["afailingcluster"] = vpc_state.ocm_mock  # type: ignore
    vpc_state.build_single_cluster.side_effect = ValueError("I am not planned!")
    with pytest.raises(ValueError):
        sut.build_desired_state_vpc(
            vpc_state.clusters, vpc_state.ocm_map, vpc_state.awsapi, account_filter=None
        )


@dataclass
class VpcSingleState:
    cluster: dict[str, Any]
    aws_account: dict[str, Any]
    ocm_mock: MagicMock
    awsapi: MagicMock


@pytest.fixture
def vpc_single_state() -> VpcSingleState:
    aws_account: dict[str, Any] = {
        "name": "accountname",
        "uid": "anuid",
        "terraformUsername": "aterraformusename",
        "automationtoken": "anautomationtoken",
        "assume_role": "arole:very:useful:indeed:it:is",
        "assume_region": "moon-tranquility-1",
        "assume_cidr": "172.25.0.0/12",
    }
    peer: dict[str, Any] = {
        "vpc": "172.17.0.0/12",
        "service": "10.1.0.0/8",
        "pod": "192.168.1.0/16",
    }
    peer_cluster: dict[str, Any] = {
        "name": "apeerclustername",
        "spec": {"region": "mars-olympus-2"},
        "network": peer,
        "peering": {
            "connections": [
                {
                    "provider": "account-vpc",
                    "name": "peername",
                    "vpc": {"$ref": "/aws/account/vpcs/mars-plain-1"},
                    "manageRoutes": True,
                },
            ]
        },
    }
    cluster: dict[str, Any] = {
        "name": "clustername",
        "spec": {"region": "mars-plain-1"},
        "network": {
            "vpc": "172.16.0.0/12",
            "service": "10.0.0.0/8",
            "pod": "192.168.0.0/16",
        },
        "peering": {
            "connections": [
                {
                    "provider": "account-vpc",
                    "name": "peername",
                    "vpc": {
                        "$ref": "/aws/account/vpcs/mars-plain-1",
                        "cidr_block": "172.30.0.0/12",
                        "vpc_id": "avpcid",
                        **peer,
                        "region": "mars-olympus-2",
                        "account": aws_account,
                    },
                    "manageRoutes": True,
                    "cluster": peer_cluster,
                },
            ]
        },
    }

    ocm_mock = MagicMock(spec=ocm.OCM)
    ocm_mock.get_aws_infrastructure_access_terraform_assume_role.side_effect = (
        lambda cluster_arg, tf_account_id, tf_user: aws_account["assume_role"]
    )

    awsapi = MagicMock(spec=aws_api.AWSApi)

    return VpcSingleState(
        cluster=cluster,
        aws_account=aws_account,
        ocm_mock=ocm_mock,
        awsapi=awsapi,
    )


def test_vpc_single_all_fine(vpc_single_state: VpcSingleState) -> None:
    expected = [
        {
            "accepter": {
                "account": {
                    "assume_cidr": "172.16.0.0/12",
                    "assume_region": "mars-plain-1",
                    "assume_role": "this:wonderful:role:hell:yeah",
                    "automationtoken": "anautomationtoken",
                    "name": "accountname",
                    "terraformUsername": "aterraformusename",
                    "uid": "anuid",
                },
                "cidr_block": "172.30.0.0/12",
                "region": "mars-olympus-2",
                "vpc_id": "avpcid",
            },
            "connection_name": "peername",
            "connection_provider": "account-vpc",
            "infra_account_name": "accountname",
            "deleted": False,
            "requester": {
                "account": {
                    "assume_cidr": "172.16.0.0/12",
                    "assume_region": "mars-plain-1",
                    "assume_role": "this:wonderful:role:hell:yeah",
                    "automationtoken": "anautomationtoken",
                    "name": "accountname",
                    "terraformUsername": "aterraformusename",
                    "uid": "anuid",
                },
                "cidr_block": "172.16.0.0/12",
                "region": "mars-plain-1",
                "route_table_ids": ["routetableid"],
                "api_security_group_id": None,
                "vpc_id": "vpcid",
            },
        }
    ]
    vpc_single_state.awsapi.get_cluster_vpc_details.return_value = (
        "vpcid",
        ["routetableid"],
        {},
        None,
    )
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role = (
        MagicMock(return_value="this:wonderful:role:hell:yeah")
    )

    rs = sut.build_desired_state_vpc_single_cluster(
        vpc_single_state.cluster,
        vpc_single_state.ocm_mock,
        vpc_single_state.awsapi,
        None,
    )
    assert rs == expected
    vpc_single_state.awsapi.get_cluster_vpc_details.assert_called_once()
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role.assert_called_once_with(
        vpc_single_state.cluster["name"],
        vpc_single_state.aws_account["uid"],
        vpc_single_state.aws_account["terraformUsername"],
    )


def test_vpc_single_private_hcp(vpc_single_state: VpcSingleState) -> None:
    vpc_single_state.cluster["spec"] = {
        "region": "mars-plain-1",
        "hypershift": True,
        "private": True,
    }
    expected = [
        {
            "accepter": {
                "account": {
                    "assume_cidr": "172.16.0.0/12",
                    "assume_region": "mars-plain-1",
                    "assume_role": "this:wonderful:role:hell:yeah",
                    "automationtoken": "anautomationtoken",
                    "name": "accountname",
                    "terraformUsername": "aterraformusename",
                    "uid": "anuid",
                },
                "cidr_block": "172.30.0.0/12",
                "region": "mars-olympus-2",
                "vpc_id": "avpcid",
            },
            "connection_name": "peername",
            "connection_provider": "account-vpc",
            "infra_account_name": "accountname",
            "deleted": False,
            "requester": {
                "account": {
                    "assume_cidr": "172.16.0.0/12",
                    "assume_region": "mars-plain-1",
                    "assume_role": "this:wonderful:role:hell:yeah",
                    "automationtoken": "anautomationtoken",
                    "name": "accountname",
                    "terraformUsername": "aterraformusename",
                    "uid": "anuid",
                },
                "cidr_block": "172.16.0.0/12",
                "region": "mars-plain-1",
                "route_table_ids": ["routetableid"],
                "api_security_group_id": "sg-vpce",
                "vpc_id": "vpcid",
            },
        }
    ]
    vpc_single_state.awsapi.get_cluster_vpc_details.return_value = (
        "vpcid",
        ["routetableid"],
        {},
        "sg-vpce",
    )
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role = (
        MagicMock(return_value="this:wonderful:role:hell:yeah")
    )

    rs = sut.build_desired_state_vpc_single_cluster(
        vpc_single_state.cluster,
        vpc_single_state.ocm_mock,
        vpc_single_state.awsapi,
        None,
    )
    assert rs == expected
    vpc_single_state.awsapi.get_cluster_vpc_details.assert_called_once()
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role.assert_called_once_with(
        vpc_single_state.cluster["name"],
        vpc_single_state.aws_account["uid"],
        vpc_single_state.aws_account["terraformUsername"],
    )


def test_vpc_single_different_provider(vpc_single_state: VpcSingleState) -> None:
    vpc_single_state.cluster["peering"]["connections"][0]["provider"] = "something-else"  # type: ignore
    assert (
        sut.build_desired_state_vpc_single_cluster(
            vpc_single_state.cluster,
            vpc_single_state.ocm_mock,
            vpc_single_state.awsapi,
            None,
        )
        == []
    )


def test_vpc_single_no_vpc_id(vpc_single_state: VpcSingleState) -> None:
    vpc_single_state.awsapi.get_cluster_vpc_details.return_value = (
        None,
        None,
        None,
        None,
    )
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role.return_value = (
        "a:role:that:you:will:like"
    )

    desired_state = sut.build_desired_state_vpc_single_cluster(
        vpc_single_state.cluster,
        vpc_single_state.ocm_mock,
        vpc_single_state.awsapi,
        None,
    )
    assert desired_state == []
    vpc_single_state.awsapi.get_cluster_vpc_details.assert_called_once()
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role.assert_called_once()


def test_vpc_single_aws_exception(vpc_single_state: VpcSingleState) -> None:
    exc_txt = "AWS Problem!"
    vpc_single_state.awsapi.get_cluster_vpc_details.side_effect = Exception(exc_txt)
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role.return_value = (
        "a:role:that:you:will:like"
    )

    with pytest.raises(Exception, match=exc_txt):
        sut.build_desired_state_vpc_single_cluster(
            vpc_single_state.cluster,
            vpc_single_state.ocm_mock,
            vpc_single_state.awsapi,
            None,
        )
    vpc_single_state.ocm_mock.get_aws_infrastructure_access_terraform_assume_role.assert_called_once()
