from unittest import TestCase
import reconcile.aws_support_cases_sos as integ


class TestSupportFunctions(TestCase):
    def test_filter_accounts(self):
        a = {"name": "a", "premiumSupport": True}
        b = {"name": "b", "premiumSupport": False}
        c = {"name": "c", "premiumSupport": None}
        d = {"name": "d"}
        accounts = [a, b, c, d]
        filtered = integ.filter_accounts(accounts)
        self.assertEqual(filtered, [a])

    def test_get_deleted_keys(self):
        a = {"name": "a", "deleteKeys": ["k1", "k2"]}
        b = {"name": "b", "deleteKeys": None}
        c = {"name": "c", "deleteKeys": []}
        accounts = [a, b, c]
        expected_result = {a["name"]: a["deleteKeys"]}
        keys_to_delete = integ.get_deleted_keys(accounts)
        self.assertEqual(keys_to_delete, expected_result)
