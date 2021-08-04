import testslide

import reconcile.utils.aws_api as awsapi
import reconcile.terraform_vpc_peerings as sut


class TestBuildDesiredStateCluster(testslide.TestCase):

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

    def test_one_cluster(self):
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).for_call(
            self.clusters[0], 'network-mgmt', {}
        ).to_return_value(
            self.aws_account
        ).and_assert_called_once()
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).for_call(
            self.peer_cluster, 'network-mgmt', {}
        ).to_return_value(self.aws_account).and_assert_called_once()
        self.find_matching_peering.for_call(
            self.clusters[0], self.clusters[0]['peering']['connections'][0],
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
        rs = sut.build_desired_state_all_clusters(self.clusters, {}, self.settings)
        self.assertEqual(rs, (expected, False))

    def test_one_cluster_no_peers(self):
        self.clusters[0]['peering']['connections'] = []
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).to_return_value(self.aws_account).and_assert_called_once()
        self.assertEqual(
            sut.build_desired_state_all_clusters(self.clusters, {}, self.settings),
            ([], False))

    def test_one_cluster_no_matches(self):
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).to_return_value(self.aws_account)
        self.mock_callable(sut, 'find_matching_peering').to_return_value(
            None
        ).and_assert_called_once()
        self.assertEqual(
            sut.build_desired_state_all_clusters(self.clusters, {}, self.settings),
            ([], True)
        )

    def test_one_cluster_no_vpc_in_aws(self):
        self.mock_callable(
            sut, 'aws_account_from_infrastructure_access'
        ).to_return_value(self.aws_account)
        self.mock_callable(sut, 'find_matching_peering').to_return_value(
            self.peer
        ).and_assert_called_once()
        self.mock_callable(
            self.awsapi, 'get_cluster_vpc_details'
        ).to_return_value((None, None, {})).and_assert_called_once()
        self.assertEqual(
            sut.build_desired_state_all_clusters(self.clusters, {}, self.settings),
            ([], True)
        )
