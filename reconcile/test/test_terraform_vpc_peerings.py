import sys
import testslide

import reconcile.terraform_vpc_peerings as integ
import reconcile.utils.terraform_client as terraform
import reconcile.utils.terrascript_client as terrascript
import reconcile.queries as queries
import reconcile.utils.ocm as ocm


class MockOCM:
    @staticmethod
    def get_aws_infrastructure_access_terraform_assume_role(cluster,
                                                            tf_account_id,
                                                            tf_user):
        return f"{cluster}/{tf_account_id}/{tf_user}"


class TestAWSAccountFromInfrastructureAccess(testslide.TestCase):
    def setUp(self):
        self.cluster = {
            'name': 'cluster',
            'spec': {
                'region': 'region'
            },
            'network': {
                'vpc': 'vpc'
            },
            'awsInfrastructureAccess': [
                {
                    'awsGroup': {
                        'account': {
                            'name': 'account',
                            'uid': 'uid',
                            'terraformUsername': 'terraform',
                            'automationToken': 'token'
                        }
                    },
                    'accessLevel': 'read-only'
                }
            ]
        }
        self.ocm_map = {
            'cluster': MockOCM()
        }

    def test_aws_account_from_infrastructure_access(self):
        expected_result = {
            'name': 'account',
            'uid': 'uid',
            'terraformUsername': 'terraform',
            'automationToken': 'token',
            'assume_role': 'cluster/uid/terraform',
            'assume_region': 'region',
            'assume_cidr': 'vpc'
        }
        account = integ.aws_account_from_infrastructure_access(
            self.cluster, 'read-only', self.ocm_map)
        self.assertEqual(account, expected_result)

    def test_aws_account_from_infrastructure_access_none(self):
        account = integ.aws_account_from_infrastructure_access(
            self.cluster, 'not-read-only', self.ocm_map)
        self.assertIsNone(account)


class TestRun(testslide.TestCase):
    def setUp(self):
        super().setUp()

        self.build_desired_state_vpc = self.mock_callable(
            integ, 'build_desired_state_vpc')
        self.build_desired_state_all_clusters = self.mock_callable(
            integ, 'build_desired_state_all_clusters')
        self.build_desired_state_vpc_mesh = self.mock_callable(
            integ, 'build_desired_state_vpc_mesh')
        self.terraform = testslide.StrictMock(terraform.TerraformClient)
        self.terrascript = testslide.StrictMock(terrascript.TerrascriptClient)
        self.mock_constructor(terraform, 'TerraformClient').to_return_value(
            self.terraform)
        self.mock_constructor(
            terrascript, 'TerrascriptClient').to_return_value(self.terrascript)
        self.ocmmap = testslide.StrictMock(ocm.OCMMap)
        self.mock_constructor(ocm, 'OCMMap').to_return_value(self.ocmmap)
        self.mock_callable(queries, 'get_aws_accounts').to_return_value([{
            "name":
            "desired_requester_account"
        }])
        self.clusters = self.mock_callable(
            queries, 'get_clusters').to_return_value([
                {"name": "aname", "peering": {"apeering"}}
            ]).and_assert_called_once()
        self.settings = self.mock_callable(
            queries, 'get_app_interface_settings').to_return_value(
                {}).and_assert_called_once()

        self.mock_callable(
            self.terrascript,
            'populate_vpc_peerings').to_return_value(
            None).and_assert_called_once()
        self.mock_callable(
            self.terrascript,
            'dump').to_return_value(None).and_assert_called_once()
        # Sigh...
        self.exit = self.mock_callable(sys, 'exit').to_raise(
            Exception("Exit called!"))
        self.addCleanup(testslide.mock_callable.unpatch_all_callable_mocks)

    def initialize_desired_states(self, error_code):
        self.build_desired_state_vpc.to_return_value(([
            {
                "connection_name": "desired_vpc_conn",
                "requester": {
                    "account": {
                        "name": "desired_requester_account"
                    }
                },
                "accepter": {
                    "account": {
                        "name": "desired_accepter_account"
                    }
                },
            },
        ], error_code))
        self.build_desired_state_all_clusters.to_return_value(([{
            "connection_name":
            "all_clusters_vpc_conn",
            "requester": {
                "account": {
                    "name": "all_clusters_requester_account"
                }
            },
            "accepter": {
                "account": {
                    "name": "all_clusters_accepter_account",
                }
            },
        }], error_code))
        self.build_desired_state_vpc_mesh.to_return_value(([{
            "connection_name": "mesh_vpc_conn",
            "requester": {
                "account": {
                    "name": "mesh_requester_account"
                },
            },
            "accepter": {
                "account": {
                    "name": "mesh_accepter_account"
                },
            }
        }], error_code))

        self.mock_callable(
            self.terrascript,
            'populate_additional_providers').for_call([
                {"name": "desired_requester_account"},
                {"name": "mesh_requester_account"},
                {"name": "all_clusters_requester_account"},
                {"name": "desired_accepter_account"},
                {"name": "mesh_accepter_account"},
                {"name": "all_clusters_accepter_account"}
            ]).to_return_value(None).and_assert_called_once()

    def test_all_fine(self):
        self.initialize_desired_states(False)
        self.mock_callable(self.terraform, 'plan').to_return_value(
            (False, False)).and_assert_called_once()
        self.mock_callable(
            self.terraform,
            'cleanup').to_return_value(None).and_assert_called_once()
        self.mock_callable(
            self.terraform,
            'apply').to_return_value(None).and_assert_called_once()
        self.exit.for_call(0).and_assert_called_once()
        with self.assertRaises(Exception):
            integ.run(False, False, False, None)

    def test_fail_state(self):
        """Ensure we don't change the world if there are failures"""
        self.initialize_desired_states(True)
        self.mock_callable(self.terraform, 'plan').to_return_value(
            (False, False)).and_assert_not_called()
        self.mock_callable(self.terraform, 'cleanup').to_return_value(
            None).and_assert_called_once()
        self.mock_callable(self.terraform, 'apply').to_return_value(
            None).and_assert_not_called()
        self.exit.for_call(1).and_assert_called_once()
        with self.assertRaises(Exception):
            integ.run(False, False, True)

    def test_dry_run(self):
        self.initialize_desired_states(False)

        self.mock_callable(self.terraform, 'plan').to_return_value(
            (False, False)).and_assert_called_once()
        self.mock_callable(self.terraform, 'cleanup').to_return_value(
            None).and_assert_called_once()
        self.mock_callable(self.terraform, 'apply').to_return_value(
            None).and_assert_not_called()
        self.exit.for_call(0).and_assert_called_once()
        with self.assertRaises(Exception):
            integ.run(True, False, False)
