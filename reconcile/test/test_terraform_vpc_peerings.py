from unittest import TestCase
import reconcile.terraform_vpc_peerings as integ


class MockOCM:
    @staticmethod
    def get_aws_infrastructure_access_terraform_assume_role(cluster,
                                                            tf_account_id,
                                                            tf_user):
        return f"{cluster}/{tf_account_id}/{tf_user}"

class TestAWSAccountFromInfrastructureAccess(TestCase):
    def test_aws_account_from_infrastructure_access(self):
        cluster = {
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
        ocm_map = {
            'cluster': MockOCM()
        }
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
            cluster, 'read-only', ocm_map)
        self.assertEqual(account, expected_result)

    def test_aws_account_from_infrastructure_access_none(self):
        cluster = {
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
        ocm_map = {
            'cluster': MockOCM()
        }
        account = integ.aws_account_from_infrastructure_access(
            cluster, 'not-read-only', ocm_map)
        self.assertIsNone(account)
