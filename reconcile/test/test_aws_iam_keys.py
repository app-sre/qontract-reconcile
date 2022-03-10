from unittest import TestCase
import reconcile.aws_iam_keys as integ


class TestSupportFunctions(TestCase):
    def test_filter_accounts_with_account_name(self):
        a = {"name": "a", "deleteKeys": ["AKIA"]}
        b = {"name": "b", "deleteKeys": ["AKIA"]}
        accounts = [a, b]
        filtered = integ.filter_accounts(accounts, a["name"])
        self.assertEqual(filtered, [a])

    def test_filter_accounts_without_account_name(self):
        a = {"name": "a", "deleteKeys": ["AKIA"]}
        b = {"name": "b", "deleteKeys": ["AKIA"]}
        accounts = [a, b]
        filtered = integ.filter_accounts(accounts, None)
        self.assertEqual(filtered, accounts)

    def test_filter_accounts_without_delete_keys(self):
        a = {"name": "a", "deleteKeys": ["AKIA"]}
        b = {"name": "b"}
        accounts = [a, b]
        filtered = integ.filter_accounts(accounts, None)
        self.assertEqual(filtered, [a])

    def test_get_keys_to_delete(self):
        a = {"name": "a", "deleteKeys": ["k1", "k2"]}
        b = {"name": "b", "deleteKeys": None}
        c = {"name": "c", "deleteKeys": []}
        accounts = [a, b, c]
        expected_result = {a["name"]: a["deleteKeys"]}
        keys_to_delete = integ.get_keys_to_delete(accounts)
        self.assertEqual(keys_to_delete, expected_result)
