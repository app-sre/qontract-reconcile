import testslide

import reconcile.utils.aws_api as awsapi
import reconcile.terraform_vpc_peerings as sut
import reconcile.utils.ocm as ocm


class TestBuildDesiredStateAllClusters(testslide.TestCase):

    def setUp(self):
        super().setUp()
        self.clusters = [
            {
                'name': 'clustername',
                'spec': {
                    'region': 'mars-plain-1',
                },
                'network': {
                    'vpc': '172.16.0.0/12',
                    'service': '10.0.0.0/8',
                    'pod': '192.168.0.0/16',
                },
                'peering': {
                    'connections': [
                        {
                            'provider': 'cluster-vpc-requester',
                            'name': 'peername',
                            'vpc': {
                                '$ref': '/aws/account/vpcs/mars-plain-1'
                            },
                            'manageRoutes': True,
                        },
                    ]
                }
            }
        ]
        self.settings = {}
        self.aws_account = {
            'name': 'accountname',
            'uid': 'anuid',
            'terraformUserName': 'aterraformusename',
            'automationtoken': 'anautomationtoken',
            'assume_role': 'arole:very:useful:indeed:it:is',
            'assume_region': 'moon-tranquility-1',
            'assume_cidr': '172.25.0.0/12',
        }

        self.peer = {
            'vpc': '172.17.0.0/12',
            'service': '10.1.0.0/8',
            'pod': '192.168.1.0/16',
        }
        self.peer_cluster = {
                'name': 'apeerclustername',
                'spec': {
                    'region': 'mars-olympus-2',
                },
                'network': self.peer,
                'peering': {
                    'connections': [
                        {
                            'provider': 'cluster-vpc-requester',
                            'name': 'peername',
                            'vpc': {
                                '$ref': '/aws/account/vpcs/mars-plain-1'
                            },
                            'manageRoutes': True,
                        },
                    ]
                }
            }
        self.clusters[0]['peering']['connections'][0]['cluster'] = \
            self.peer_cluster
        self.build_single_cluster = self.mock_callable(
            sut, 'build_desired_state_single_cluster'
        )
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)

    def test_one_cluster(self):

        expected = [
            {
                'connection_provider': 'cluster-vpc-requester',
                'connection_name': 'peername',
                'requester': {
                    'vpc_id': 'vpcid',
                    'route_table_ids': ['route_table_id'],
                    'region': 'mars-plain-1',
                    'cidr_block': '172.16.0.0/12',
                    'peer_owner_id': 'it',
                    'account': {
                        'assume_region': 'mars-olympus-2',
                        'assume_cidr': '172.17.0.0/12',
                        **self.aws_account,
                    }
                },
                'accepter': {
                    'vpc_id': 'acceptervpcid',
                    'route_table_ids': ['accepterroutetableid'],
                    'region': 'mars-olympus-2',
                    'cidr_block': '172.17.0.0/12',
                    'account': {
                        'assume_region': 'mars-olympus-2',
                        'assume_cidr': '172.17.0.0/12',
                        **self.aws_account,
                    }
                },
                'deleted': False
            }
        ]
        self.build_single_cluster.for_call(
            self.clusters[0], {}, self.settings
        ).to_return_value(expected).and_assert_called_once()

        rs = sut.build_desired_state_all_clusters(
            self.clusters, {}, self.settings
        )
        self.assertEqual(rs, (expected, False))

    def test_one_cluster_failing(self):
        self.build_single_cluster.to_raise(
            sut.BadTerraformPeeringState
        ).and_assert_called_once()
        self.assertEqual(
            sut.build_desired_state_all_clusters(
                self.clusters, {}, self.settings
                ),
            ([], True))


class TestBuildDesiredStateSingleCluster(testslide.TestCase):
    def setUp(self):
        super().setUp()
        self.cluster = {
            'name': 'clustername',
            'spec': {
                'region': 'mars-plain-1',
            },
            'network': {
                'vpc': '172.16.0.0/12',
                'service': '10.0.0.0/8',
                'pod': '192.168.0.0/16',
            },
            'peering': {
                'connections': [
                    {
                        'provider': 'cluster-vpc-requester',
                        'name': 'peername',
                        'vpc': {
                            '$ref': '/aws/account/vpcs/mars-plain-1'
                        },
                        'manageRoutes': True,
                    },
                ]
            }
        }
        self.peer = {
            'vpc': '172.17.0.0/12',
            'service': '10.1.0.0/8',
            'pod': '192.168.1.0/16',
        }
        self.peer_cluster = {
                'name': 'apeerclustername',
                'spec': {
                    'region': 'mars-olympus-2',
                },
                'network': self.peer,
                'peering': {
                    'connections': [
                        {
                            'provider': 'cluster-vpc-requester',
                            'name': 'peername',
                            'vpc': {
                                '$ref': '/aws/account/vpcs/mars-plain-1'
                            },
                            'manageRoutes': True,
                        },
                    ]
                }
            }
        self.cluster['peering']['connections'][0]['cluster'] = \
            self.peer_cluster
        self.aws_account = {
            'name': 'accountname',
            'uid': 'anuid',
            'terraformUserName': 'aterraformusename',
            'automationtoken': 'anautomationtoken',
            'assume_role': 'arole:very:useful:indeed:it:is',
            'assume_region': 'moon-tranquility-1',
            'assume_cidr': '172.25.0.0/12',
        }
        self.peer_vpc = {
            'cidr_block': '172.30.0.0/12',
            'vpc_id': 'peervpcid',
            'route_table_ids': ['peer_route_table_id']
        }
        self.settings = {}
        self.awsapi = testslide.StrictMock(awsapi.AWSApi)
        self.mock_constructor(
            awsapi, 'AWSApi'
        ).to_return_value(self.awsapi)
        self.maxDiff = None
        self.find_matching_peering = self.mock_callable(
            sut, 'find_matching_peering'
        )
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)

    def test_base(self):
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).for_call(
            self.cluster, 'network-mgmt', {}
        ).to_return_value(
            self.aws_account
        ).and_assert_called_once()
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).for_call(
            self.peer_cluster, 'network-mgmt', {}
        ).to_return_value(self.aws_account).and_assert_called_once()
        self.find_matching_peering.for_call(
            self.cluster, self.cluster['peering']['connections'][0],
            self.peer_cluster,
            'cluster-vpc-accepter'
        ).to_return_value(self.peer).and_assert_called_once()
        aws_req = {
            'assume_region': 'mars-plain-1',
            'assume_cidr': '172.16.0.0/12',
            **self.aws_account
        }
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).for_call(
            aws_req, route_tables=True
        ).to_return_value(
            ('vpcid', ['route_table_id'], {})
        ).and_assert_called_once()
        aws_req = {
            'assume_region': 'mars-olympus-2',
            'assume_cidr': '172.17.0.0/12',
            **self.aws_account
        }
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).for_call(
            aws_req, route_tables=None
        ).to_return_value(
            ('acceptervpcid', ['accepterroutetableid'], {})
        ).and_assert_called_once()

        expected = [
            {
                'connection_provider': 'cluster-vpc-requester',
                'connection_name': 'peername',
                'requester': {
                    'vpc_id': 'vpcid',
                    'route_table_ids': ['route_table_id'],
                    'region': 'mars-plain-1',
                    'cidr_block': '172.16.0.0/12',
                    'peer_owner_id': 'it',
                    'account': {
                        'assume_region': 'mars-olympus-2',
                        'assume_cidr': '172.17.0.0/12',
                        **self.aws_account,
                    }
                },
                'accepter': {
                    'vpc_id': 'acceptervpcid',
                    'route_table_ids': ['accepterroutetableid'],
                    'region': 'mars-olympus-2',
                    'cidr_block': '172.17.0.0/12',
                    'account': {
                        'assume_region': 'mars-olympus-2',
                        'assume_cidr': '172.17.0.0/12',
                        **self.aws_account,
                    }
                },
                'deleted': False
            }
        ]
        rs = sut.build_desired_state_single_cluster(
            self.cluster, {}, self.settings
        )
        self.assertEqual(rs, expected)

    def test_no_peerings(self):
        self.cluster['peering']['connections'] = []
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).to_return_value(self.aws_account).and_assert_called_once()
        rs = sut.build_desired_state_single_cluster(
            self.cluster, {}, self.settings
        )
        self.assertEqual(rs, [])

    def test_no_matches(self):
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).to_return_value(self.aws_account)
        self.find_matching_peering.to_return_value(None)
        with self.assertRaises(sut.BadTerraformPeeringState):
            sut.build_desired_state_single_cluster(
                self.cluster, {}, self.settings
            )

    def test_no_vpc_in_aws(self):
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).to_return_value(self.aws_account)
        self.find_matching_peering.to_return_value(
            self.peer
        ).and_assert_called_once()
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).to_return_value((None, None, {})).and_assert_called_once()

        with self.assertRaises(sut.BadTerraformPeeringState):
            sut.build_desired_state_single_cluster(
                self.cluster, {}, self.settings
            )

    def test_no_peer_account(self):
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).for_call(
            self.cluster, 'network-mgmt', {}
        ).to_return_value(self.aws_account)
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).for_call(
            self.peer_cluster, 'network-mgmt', {}
        ).to_return_value(None).and_assert_called_once()
        self.find_matching_peering.to_return_value(self.peer)
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).to_return_value(
            ('vpcid', ['route_table_id'], {})
        ).and_assert_called_once()

        with self.assertRaises(sut.BadTerraformPeeringState):
            sut.build_desired_state_single_cluster(
                self.cluster, {}, self.settings
            )

class TestBuildDesiredStateVpcMesh(testslide.TestCase):

    def setUp(self):
        super().setUp()
        self.clusters = [
            {
                'name': 'clustername',
                'spec': {
                    'region': 'mars-plain-1',
                },
                'network': {
                    'vpc': '172.16.0.0/12',
                    'service': '10.0.0.0/8',
                    'pod': '192.168.0.0/16',
                },
                'peering': {
                    'connections': [
                        {
                            'provider': 'account-vpc-mesh',
                            'name': 'peername',
                            'vpc': {
                                '$ref': '/aws/account/vpcs/mars-plain-1'
                            },
                            'manageRoutes': True,
                            'tags': '["tag1"]',
                        },
                    ]
                }
            }
        ]
        self.peer = {
            'vpc': '172.17.0.0/12',
            'service': '10.1.0.0/8',
            'pod': '192.168.1.0/16',
        }
        self.peer_cluster = {
            'name': 'apeerclustername',
            'spec': {
                'region': 'mars-olympus-2',
            },
            'network': self.peer,
            'peering': {
                'connections': [
                    {
                        'provider': 'cluster-vpc-requester',
                        'name': 'peername',
                        'vpc': {
                            '$ref': '/aws/account/vpcs/mars-plain-1'
                        },
                        'manageRoutes': True,
                        'tags': '["tag1"]',
                    },
                ]
            }
        }

        self.aws_account = {
            'name': 'accountname',
            'uid': 'anuid',
            'terraformUsername': 'aterraformusename',
            'automationtoken': 'anautomationtoken',
            'assume_role': 'arole:very:useful:indeed:it:is',
            'assume_region': 'moon-tranquility-1',
            'assume_cidr': '172.25.0.0/12',
        }
        self.peer_account = {
            'name': 'peer_account',
            'uid': 'peeruid',
            'terraformUsername': 'peerterraformusename',
            'automationtoken': 'peeranautomationtoken',
            'assume_role': 'a:peer:role:indeed:it:is',
            'assume_region': 'mars-hellas-1',
            'assume_cidr': '172.25.0.0/12',
        }
        self.clusters[0]['peering']['connections'][0]['cluster'] = \
            self.peer_cluster
        self.clusters[0]['peering']['connections'][0]['account'] = \
            self.peer_account
        self.peer_vpc = {
            'cidr_block': '172.30.0.0/12',
            'vpc_id': 'peervpcid',
            'route_table_ids': ['peer_route_table_id']
        }
        self.settings = {}
        self.awsapi = testslide.StrictMock(awsapi.AWSApi)
        self.mock_constructor(
            awsapi, 'AWSApi'
        ).to_return_value(self.awsapi)
        self.maxDiff = None
        self.find_matching_peering = self.mock_callable(
            sut, 'find_matching_peering'
        )
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)
        self.ocm = testslide.StrictMock(template=ocm.OCM)
        self.ocm_map = {
            'clustername': self.ocm
        }
        self.ocm.get_aws_infrastructure_access_terraform_assume_role = \
            lambda cluster, uid, tfuser: self.peer_account['assume_role']
        self.account_vpcs = [
            {
                'vpc_id': 'vpc1',
                'region': 'moon-dark-1',
                'cidr_block': '192.168.3.0/24',
                'route_table_ids': ['vpc1_route_table'],
            },
            {
                'vpc_id': 'vpc2',
                'region': 'mars-utopia-2',
                'cidr_block': '192.168.4.0/24',
                'route_table_ids': ['vpc2_route_table'],
            }
        ]


    def test_one_cluster(self):
        req_account = {
            **self.peer_account,
            'assume_region': 'mars-plain-1',
            'assume_cidr': '172.16.0.0/12',
        }
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).for_call(
            req_account, route_tables=True
        ).to_return_value(
            ('vpc_id', ['route_table_id'], 'subnet_id')
        ).and_assert_called_once()

        self.mock_callable(
            self.awsapi, 'get_vpcs_details'
        ).for_call(
            req_account, tags=['tag1'], route_tables=True
        ).to_return_value(self.account_vpcs).and_assert_called_once()

        expected = [
            {
                'connection_provider': 'account-vpc-mesh',
                'connection_name': 'peername_peer_account-vpc1',
                'requester': {
                    'vpc_id': 'vpc_id',
                    'route_table_ids': ['route_table_id'],
                    'account': self.peer_account,
                    'region': 'mars-plain-1',
                    'cidr_block': '172.16.0.0/12',
                },
                'accepter': {
                    'vpc_id': 'vpc1',
                    'region': 'moon-dark-1',
                    'cidr_block': '192.168.3.0/24',
                    'route_table_ids': ['vpc1_route_table'],
                    'account': self.peer_account,
                },
                'deleted': False,
            },
            {
                'connection_provider': 'account-vpc-mesh',
                'connection_name': 'peername_peer_account-vpc2',
                'requester': {
                    'vpc_id': 'vpc_id',
                    'route_table_ids': ['route_table_id'],
                    'account': self.peer_account,
                    'region': 'mars-plain-1',
                    'cidr_block': '172.16.0.0/12',
                },
                'accepter': {
                    'vpc_id': 'vpc2',
                    'region': 'mars-utopia-2',
                    'cidr_block': '192.168.4.0/24',
                    'route_table_ids': ['vpc2_route_table'],
                    'account': self.peer_account,
                },
                'deleted': False,
            }
        ]
        rs = sut.build_desired_state_vpc_mesh(self.clusters, self.ocm_map, {})
        self.assertEqual(rs, (expected, False))

    def test_no_peering_connections(self):
        self.clusters[0]['peering']['connections'] = []
        rs = sut.build_desired_state_vpc_mesh(self.clusters, self.ocm_map, {})
        self.assertEqual(rs, ([], False))

    def test_no_peer_vpc_id(self):
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).to_return_value((None, [None], None)).and_assert_called_once()

        rs = sut.build_desired_state_vpc_mesh(self.clusters, self.ocm_map, {})
        self.assertEqual(rs, ([], True))

    def test_no_vpcs_in_account(self):
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).to_return_value(
            ('vpc_id', ['route_table_id'], 'subnet_id')
        ).and_assert_called_once()

        self.mock_callable(
            self.awsapi, 'get_vpcs_details'
        ).to_return_value([]).and_assert_called_once()

        rs = sut.build_desired_state_vpc_mesh(self.clusters, self.ocm_map, {})
        self.assertEqual(rs, ([], False))
