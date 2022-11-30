import pytest
import testslide

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


def test_c2c_all_clusters(mocker):
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
        .auto_speced_mock(mocker)
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
        .auto_speced_mock(mocker)
    )

    expected = [
        {
            "connection_provider": "cluster-vpc-requester",
            "connection_name": "peername",
            "requester": {
                "cidr_block": "requester_vpc",
                "region": "region",
                "vpc_id": "requester_vpc_id",
                "route_table_ids": ["requester_rt_id"],
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
        [requester_cluster], ocm_map, awsapi, account_filter=None
    )
    assert result == expected
    assert not error

    # correct account filter
    result, error = sut.build_desired_state_all_clusters(
        [requester_cluster], ocm_map, awsapi, account_filter="acc"
    )
    assert result == expected
    assert not error

    # wrong account filter
    result, error = sut.build_desired_state_all_clusters(
        [requester_cluster], ocm_map, awsapi, account_filter="another_account"
    )
    assert not result
    assert not error


def test_c2c_one_cluster_failing_recoverable(mocker):
    """
    in this scenario, the handling of a single cluster fails with known
    exceptions
    """
    build_desired_state_single_cluster = mocker.patch.object(
        sut, "build_desired_state_single_cluster"
    )
    build_desired_state_single_cluster.side_effect = sut.BadTerraformPeeringState(
        "something bad"
    )

    result, error = sut.build_desired_state_all_clusters(
        [{"name": "cluster"}], {}, {}, account_filter=None
    )

    assert not result
    assert error


def test_c2c_one_cluster_failing_weird(mocker):
    """
    in this scenario, the handling of a single cluster fails with unexpected
    exceptions
    """
    build_desired_state_single_cluster = mocker.patch.object(
        sut, "build_desired_state_single_cluster"
    )
    SOMETHING_UNEXPECTED = "nobody expects the spanish inquisition"
    build_desired_state_single_cluster.side_effect = ValueError(SOMETHING_UNEXPECTED)

    with pytest.raises(ValueError) as ex:
        sut.build_desired_state_all_clusters(
            [{"name": "cluster"}], {}, {}, account_filter=None
        )

    assert str(ex.value) == SOMETHING_UNEXPECTED


def test_c2c_base(mocker):
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
        .auto_speced_mock(mocker)
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
        .auto_speced_mock(mocker)
    )

    expected = [
        {
            "connection_provider": "cluster-vpc-requester",
            "connection_name": "peername",
            "requester": {
                "cidr_block": "requester_vpc",
                "region": "region",
                "vpc_id": "requester_vpc_id",
                "route_table_ids": ["requester_rt_id"],
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
        requester_cluster, ocm, awsapi, account_filter=None
    )
    assert result == expected

    # correct account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster, ocm, awsapi, account_filter="acc"
    )
    assert result == expected

    # correct account filtering
    result = sut.build_desired_state_single_cluster(
        requester_cluster, ocm, awsapi, account_filter="another_account"
    )
    assert not result


def test_c2c_no_peerings(mocker):
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
        MockOCM().auto_speced_mock(mocker),
        MockAWSAPI().auto_speced_mock(mocker),
        account_filter=None,
    )
    assert not result


def test_c2c_no_matches(mocker):
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

    with pytest.raises(sut.BadTerraformPeeringState) as ex:
        sut.build_desired_state_single_cluster(
            requester_cluster,
            MockOCM().auto_speced_mock(mocker),
            MockAWSAPI().auto_speced_mock(mocker),
            account_filter=None,
        )
    assert str(ex.value).startswith("[no_matching_peering]")


def test_c2c_no_vpc_in_aws(mocker):
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
        .auto_speced_mock(mocker)
    )

    awsapi = MockAWSAPI().auto_speced_mock(mocker)

    with pytest.raises(sut.BadTerraformPeeringState) as ex:
        sut.build_desired_state_single_cluster(
            requester_cluster, ocm, awsapi, account_filter=None
        )
    assert str(ex.value).endswith("could not find VPC ID for cluster")


def test_c2c_no_peer_account(mocker):
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

    ocm = MockOCM().auto_speced_mock(mocker)
    awsapi = MockAWSAPI().auto_speced_mock(mocker)

    with pytest.raises(sut.BadTerraformPeeringState) as ex:
        sut.build_desired_state_single_cluster(
            requester_cluster, ocm, awsapi, account_filter=None
        )
    assert str(ex.value).startswith("[no_account_available]")


class TestBuildDesiredStateVpcMesh(testslide.TestCase):
    def setUp(self):
        super().setUp()
        self.clusters = [
            {
                "name": "clustername",
                "spec": {
                    "region": "mars-plain-1",
                },
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
                        },
                    ]
                },
            }
        ]
        self.peer = {
            "vpc": "172.17.0.0/12",
            "service": "10.1.0.0/8",
            "pod": "192.168.1.0/16",
        }
        self.peer_cluster = {
            "name": "apeerclustername",
            "spec": {
                "region": "mars-olympus-2",
            },
            "network": self.peer,
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

        self.aws_account = {
            "name": "accountname",
            "uid": "anuid",
            "terraformUsername": "aterraformusename",
            "automationtoken": "anautomationtoken",
            "assume_role": "arole:very:useful:indeed:it:is",
            "assume_region": "moon-tranquility-1",
            "assume_cidr": "172.25.0.0/12",
        }
        self.peer_account = {
            "name": "peer_account",
            "uid": "peeruid",
            "terraformUsername": "peerterraformusename",
            "automationtoken": "peeranautomationtoken",
            "assume_role": "a:peer:role:indeed:it:is",
            "assume_region": "mars-hellas-1",
            "assume_cidr": "172.25.0.0/12",
        }
        self.clusters[0]["peering"]["connections"][0]["cluster"] = self.peer_cluster
        self.clusters[0]["peering"]["connections"][0]["account"] = self.peer_account
        self.peer_vpc = {
            "cidr_block": "172.30.0.0/12",
            "vpc_id": "peervpcid",
            "route_table_ids": ["peer_route_table_id"],
        }
        self.vpc_mesh_single_cluster = self.mock_callable(
            sut, "build_desired_state_vpc_mesh_single_cluster"
        )
        self.maxDiff = None
        self.ocm = testslide.StrictMock(ocm.OCM)
        self.ocm_map = {"clustername": self.ocm}
        self.ocm.get_aws_infrastructure_access_terraform_assume_role = (
            lambda cluster, uid, tfuser: self.peer_account["assume_role"]
        )
        self.awsapi = testslide.StrictMock(aws_api.AWSApi)
        self.account_vpcs = [
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
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)

    def test_all_fine(self):
        expected = [
            {
                "connection_provider": "account-vpc-mesh",
                "connection_name": "peername_peer_account-vpc1",
                "requester": {
                    "vpc_id": "vpc_id",
                    "route_table_ids": ["route_table_id"],
                    "account": self.peer_account,
                    "region": "mars-plain-1",
                    "cidr_block": "172.16.0.0/12",
                },
                "accepter": {
                    "vpc_id": "vpc1",
                    "region": "moon-dark-1",
                    "cidr_block": "192.168.3.0/24",
                    "route_table_ids": ["vpc1_route_table"],
                    "account": self.peer_account,
                },
                "deleted": False,
            },
            {
                "connection_provider": "account-vpc-mesh",
                "connection_name": "peername_peer_account-vpc2",
                "requester": {
                    "vpc_id": "vpc_id",
                    "route_table_ids": ["route_table_id"],
                    "account": self.peer_account,
                    "region": "mars-plain-1",
                    "cidr_block": "172.16.0.0/12",
                },
                "accepter": {
                    "vpc_id": "vpc2",
                    "region": "mars-utopia-2",
                    "cidr_block": "192.168.4.0/24",
                    "route_table_ids": ["vpc2_route_table"],
                    "account": self.peer_account,
                },
                "deleted": False,
            },
        ]
        self.vpc_mesh_single_cluster.for_call(
            self.clusters[0], self.ocm, self.awsapi, None
        ).to_return_value(expected)

        rs = sut.build_desired_state_vpc_mesh(
            self.clusters,
            self.ocm_map,
            self.awsapi,
            None,
        )
        self.assertEqual(rs, (expected, False))

    def test_cluster_raises(self):
        self.vpc_mesh_single_cluster.to_raise(
            sut.BadTerraformPeeringState("This is wrong")
        )
        rs = sut.build_desired_state_vpc_mesh(
            self.clusters, self.ocm_map, self.awsapi, None
        )
        self.assertEqual(rs, ([], True))

    def test_cluster_raises_unexpected(self):
        self.vpc_mesh_single_cluster.to_raise(ValueError("Nope"))
        with self.assertRaises(ValueError):
            sut.build_desired_state_vpc_mesh(
                self.clusters, self.ocm_map, self.awsapi, None
            )


class TestBuildDesiredStateVpcMeshSingleCluster(testslide.TestCase):
    def setUp(self):
        super().setUp()
        self.cluster = {
            "name": "clustername",
            "spec": {
                "region": "mars-plain-1",
            },
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
                    },
                ]
            },
        }
        self.peer = {
            "vpc": "172.17.0.0/12",
            "service": "10.1.0.0/8",
            "pod": "192.168.1.0/16",
        }
        self.peer_cluster = {
            "name": "apeerclustername",
            "spec": {
                "region": "mars-olympus-2",
            },
            "network": self.peer,
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
        self.awsapi = testslide.StrictMock(aws_api.AWSApi)
        self.mock_constructor(aws_api, "AWSApi").to_return_value(self.awsapi)
        self.find_matching_peering = self.mock_callable(sut, "find_matching_peering")
        self.aws_account = {
            "name": "accountname",
            "uid": "anuid",
            "terraformUsername": "aterraformusename",
            "automationtoken": "anautomationtoken",
            "assume_role": "arole:very:useful:indeed:it:is",
            "assume_region": "moon-tranquility-1",
            "assume_cidr": "172.25.0.0/12",
        }
        self.peer_account = {
            "name": "peer_account",
            "uid": "peeruid",
            "terraformUsername": "peerterraformusename",
            "automationtoken": "peeranautomationtoken",
            "assume_role": "a:peer:role:indeed:it:is",
            "assume_region": "mars-hellas-1",
            "assume_cidr": "172.25.0.0/12",
        }
        self.cluster["peering"]["connections"][0]["cluster"] = self.peer_cluster
        self.cluster["peering"]["connections"][0]["account"] = self.peer_account
        self.peer_vpc = {
            "cidr_block": "172.30.0.0/12",
            "vpc_id": "peervpcid",
            "route_table_ids": ["peer_route_table_id"],
        }
        self.maxDiff = None
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)
        self.ocm = testslide.StrictMock(template=ocm.OCM)
        self.ocm.get_aws_infrastructure_access_terraform_assume_role = (
            lambda cluster, uid, tfuser: self.peer_account["assume_role"]
        )
        self.account_vpcs = [
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

    def test_one_cluster(self):

        req_account = {
            **self.peer_account,
            "assume_region": "mars-plain-1",
            "assume_cidr": "172.16.0.0/12",
        }
        self.mock_callable(self.awsapi, "get_cluster_vpc_details").for_call(
            req_account, route_tables=True
        ).to_return_value(
            ("vpc_id", ["route_table_id"], "subnet_id")
        ).and_assert_called_once()

        self.mock_callable(self.awsapi, "get_vpcs_details").for_call(
            req_account, tags=["tag1"], route_tables=True
        ).to_return_value(self.account_vpcs).and_assert_called_once()

        expected = [
            {
                "connection_provider": "account-vpc-mesh",
                "connection_name": "peername_peer_account-vpc1",
                "requester": {
                    "vpc_id": "vpc_id",
                    "route_table_ids": ["route_table_id"],
                    "account": self.peer_account,
                    "region": "mars-plain-1",
                    "cidr_block": "172.16.0.0/12",
                },
                "accepter": {
                    "vpc_id": "vpc1",
                    "region": "moon-dark-1",
                    "cidr_block": "192.168.3.0/24",
                    "route_table_ids": ["vpc1_route_table"],
                    "account": self.peer_account,
                },
                "deleted": False,
            },
            {
                "connection_provider": "account-vpc-mesh",
                "connection_name": "peername_peer_account-vpc2",
                "requester": {
                    "vpc_id": "vpc_id",
                    "route_table_ids": ["route_table_id"],
                    "account": self.peer_account,
                    "region": "mars-plain-1",
                    "cidr_block": "172.16.0.0/12",
                },
                "accepter": {
                    "vpc_id": "vpc2",
                    "region": "mars-utopia-2",
                    "cidr_block": "192.168.4.0/24",
                    "route_table_ids": ["vpc2_route_table"],
                    "account": self.peer_account,
                },
                "deleted": False,
            },
        ]

        rs = sut.build_desired_state_vpc_mesh_single_cluster(
            self.cluster, self.ocm, self.awsapi, None
        )
        self.assertEqual(rs, expected)

    def test_no_peering_connections(self):
        self.cluster["peering"]["connections"] = []
        rs = sut.build_desired_state_vpc_mesh_single_cluster(
            self.cluster, self.ocm, self.awsapi, None
        )
        self.assertEqual(rs, [])

    def test_no_peer_vpc_id(self):
        self.mock_callable(self.awsapi, "get_cluster_vpc_details").to_return_value(
            (None, [None], None)
        ).and_assert_called_once()

        with self.assertRaises(sut.BadTerraformPeeringState):
            sut.build_desired_state_vpc_mesh_single_cluster(
                self.cluster, self.ocm, self.awsapi, None
            )


class TestBuildDesiredStateVpc(testslide.TestCase):
    def setUp(self):
        super().setUp()
        self.peer = {
            "vpc": "172.17.0.0/12",
            "service": "10.1.0.0/8",
            "pod": "192.168.1.0/16",
        }
        self.aws_account = {
            "name": "accountname",
            "uid": "anuid",
            "terraformUsername": "aterraformusename",
            "automationtoken": "anautomationtoken",
            "assume_role": "arole:very:useful:indeed:it:is",
            "assume_region": "moon-tranquility-1",
            "assume_cidr": "172.25.0.0/12",
        }

        self.clusters = [
            {
                "name": "clustername",
                "spec": {
                    "region": "mars-plain-1",
                },
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
                                **self.peer,
                                "region": "mars-olympus-2",
                                "account": self.aws_account,
                            },
                            "manageRoutes": True,
                        },
                    ]
                },
            }
        ]

        self.peer_cluster = {
            "name": "apeerclustername",
            "spec": {
                "region": "mars-olympus-2",
            },
            "network": self.peer,
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
        self.clusters[0]["peering"]["connections"][0]["cluster"] = self.peer_cluster
        self.build_single_cluster = self.mock_callable(
            sut, "build_desired_state_single_cluster"
        )
        self.ocm = testslide.StrictMock(template=ocm.OCM)
        self.ocm_map = {"clustername": self.ocm}
        self.awsapi = testslide.StrictMock(aws_api.AWSApi)

        self.build_single_cluster = self.mock_callable(
            sut, "build_desired_state_vpc_single_cluster"
        )
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)
        self.maxDiff = None

    def test_all_fine(self):
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
        self.build_single_cluster.for_call(
            self.clusters[0], self.ocm, self.awsapi, None
        ).to_return_value(expected).and_assert_called_once()

        rs = sut.build_desired_state_vpc(
            self.clusters, self.ocm_map, self.awsapi, account_filter=None
        )
        self.assertEqual(rs, (expected, False))

    def test_cluster_fails(self):
        self.build_single_cluster.to_raise(
            sut.BadTerraformPeeringState("I have failed")
        )

        self.assertEqual(
            sut.build_desired_state_vpc(
                self.clusters, self.ocm_map, self.awsapi, account_filter=None
            ),
            ([], True),
        )

    def test_error_persists(self):
        self.clusters.append(self.clusters[0].copy())
        self.clusters[1]["name"] = "afailingcluster"
        self.ocm_map["afailingcluster"] = self.ocm
        self.build_single_cluster.for_call(
            self.clusters[0], self.ocm, self.awsapi, None
        ).to_return_value([{"a dict": "a value"}]).and_assert_called_once()
        self.mock_callable(sut, "build_desired_state_vpc_single_cluster").for_call(
            self.clusters[1],
            self.ocm,
            self.awsapi,
            None,
        ).to_raise(sut.BadTerraformPeeringState("Fail!")).and_assert_called_once()

        self.assertEqual(
            sut.build_desired_state_vpc(
                self.clusters, self.ocm_map, self.awsapi, account_filter=None
            ),
            ([{"a dict": "a value"}], True),
        )

    def test_other_exceptions_raise(self):
        self.clusters.append(self.clusters[0].copy())
        self.clusters[1]["name"] = "afailingcluster"
        self.ocm_map["afailingcluster"] = self.ocm
        self.build_single_cluster.for_call(
            self.clusters[0], self.ocm, self.awsapi, None
        ).to_raise(ValueError("I am not planned!")).and_assert_called_once()
        with self.assertRaises(ValueError):
            sut.build_desired_state_vpc(
                self.clusters, self.ocm_map, self.awsapi, account_filter=None
            )


class TestBuildDesiredStateVpcSingleCluster(testslide.TestCase):
    def setUp(self):
        super().setUp()
        self.peer = {
            "vpc": "172.17.0.0/12",
            "service": "10.1.0.0/8",
            "pod": "192.168.1.0/16",
        }
        self.aws_account = {
            "name": "accountname",
            "uid": "anuid",
            "terraformUsername": "aterraformusename",
            "automationtoken": "anautomationtoken",
            "assume_role": "arole:very:useful:indeed:it:is",
            "assume_region": "moon-tranquility-1",
            "assume_cidr": "172.25.0.0/12",
        }

        self.cluster = {
            "name": "clustername",
            "spec": {
                "region": "mars-plain-1",
            },
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
                            **self.peer,
                            "region": "mars-olympus-2",
                            "account": self.aws_account,
                        },
                        "manageRoutes": True,
                    },
                ]
            },
        }

        self.peer_cluster = {
            "name": "apeerclustername",
            "spec": {
                "region": "mars-olympus-2",
            },
            "network": self.peer,
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
        self.cluster["peering"]["connections"][0]["cluster"] = self.peer_cluster
        self.build_single_cluster = self.mock_callable(
            sut, "build_desired_state_single_cluster"
        )
        self.ocm = testslide.StrictMock(template=ocm.OCM)
        self.awsapi = testslide.StrictMock(aws_api.AWSApi)
        self.mock_constructor(aws_api, "AWSApi").to_return_value(self.awsapi)
        self.ocm.get_aws_infrastructure_access_terraform_assume_role = (
            lambda cluster, uid, tfuser: self.aws_account["assume_role"]
        )
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)
        self.maxDiff = None

    def test_all_fine(self):
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
        self.mock_callable(self.awsapi, "get_cluster_vpc_details",).for_call(
            self.aws_account, route_tables=True
        ).to_return_value(("vpcid", ["routetableid"], {})).and_assert_called_once()
        self.mock_callable(
            self.ocm, "get_aws_infrastructure_access_terraform_assume_role"
        ).for_call(
            self.cluster["name"],
            self.aws_account["uid"],
            self.aws_account["terraformUsername"],
        ).to_return_value(
            "this:wonderful:role:hell:yeah"
        ).and_assert_called_once()
        rs = sut.build_desired_state_vpc_single_cluster(
            self.cluster, self.ocm, self.awsapi, None
        )
        self.assertEqual(rs, expected)

    def test_different_provider(self):
        self.cluster["peering"]["connections"][0]["provider"] = "something-else"
        self.assertEqual(
            sut.build_desired_state_vpc_single_cluster(
                self.cluster, self.ocm, self.awsapi, None
            ),
            [],
        )

    def test_no_vpc_id(self):
        self.mock_callable(self.awsapi, "get_cluster_vpc_details").to_return_value(
            (None, None, None)
        ).and_assert_called_once()

        self.mock_callable(
            self.ocm, "get_aws_infrastructure_access_terraform_assume_role"
        ).to_return_value("a:role:that:you:will:like").and_assert_called_once()

        with self.assertRaises(sut.BadTerraformPeeringState):
            sut.build_desired_state_vpc_single_cluster(
                self.cluster, self.ocm, self.awsapi, None
            )
