from unittest import TestCase
import reconcile.utils.terrascript_client as tsclient


class TestSupportFunctions(TestCase):

    def test_sanitize_resource_with_dots(self):
        self.assertEqual(
            tsclient.safe_resource_id("foo.example.com"),
            "foo_example_com"
        )

    def test_sanitize_resource_with_wildcard(self):
        self.assertEqual(
            tsclient.safe_resource_id("*.foo.example.com"),
            "_star_foo_example_com"
        )

    def test_aws_username_org(self):
        ts = tsclient.TerrascriptClient('', '', 1, [])
        result = 'org'
        user = {
            'org_username': result
        }
        self.assertEqual(ts._get_aws_username(user), result)

    def test_aws_username_aws(self):
        ts = tsclient.TerrascriptClient('', '', 1, [])
        result = 'aws'
        user = {
            'org_username': 'org',
            'aws_username': result
        }
        self.assertEqual(ts._get_aws_username(user), result)
