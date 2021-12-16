from unittest import TestCase
import reconcile.utils.terraform_client as tfclient


class TestDeletionApproved(TestCase):

    def test_no_deletion_approvals(self):
        account = {
            'name': 'a1',
            'deletionApprovals': []
        }
        tf = tfclient.TerraformClient(
            'integ',
            'v1',
            'integ_pfx',
            [account],
            {},
            1
        )
        result = tf.deletion_approved('a1', 't1', 'n1')
        self.assertFalse(result)

    def test_deletion_not_approved(self):
        account = {
            'name': 'a1',
            'deletionApprovals': [
                {
                    'type': 't1',
                    'name': 'n1',
                    'expiration': '2000-01-01'
                }
            ]
        }
        tf = tfclient.TerraformClient(
            'integ',
            'v1',
            'integ_pfx',
            [account],
            {},
            1
        )
        result = tf.deletion_approved('a1', 't2', 'n2')
        self.assertFalse(result)

    def test_deletion_approved_expired(self):
        account = {
            'name': 'a1',
            'deletionApprovals': [
                {
                    'type': 't1',
                    'name': 'n1',
                    'expiration': '2000-01-01'
                }
            ]
        }
        tf = tfclient.TerraformClient(
            'integ',
            'v1',
            'integ_pfx',
            [account],
            {},
            1
        )
        result = tf.deletion_approved('a1', 't1', 'n1')
        self.assertFalse(result)

    def test_deletion_approved(self):
        account = {
            'name': 'a1',
            'deletionApprovals': [
                {
                    'type': 't1',
                    'name': 'n1',
                    'expiration': '2500-01-01'
                }
            ]
        }
        tf = tfclient.TerraformClient(
            'integ',
            'v1',
            'integ_pfx',
            [account],
            {},
            1
        )
        result = tf.deletion_approved('a1', 't1', 'n1')
        self.assertTrue(result)
