from typing import Any
from unittest import TestCase

import reconcile.aws_support_cases_sos as integ


class TestSupportFunctions(TestCase):
    def test_filter_accounts(self) -> None:
        a: dict[str, Any] = {"name": "a", "premiumSupport": True}
        b: dict[str, Any] = {"name": "b", "premiumSupport": False}
        c: dict[str, Any] = {"name": "c", "premiumSupport": None}
        d: dict[str, Any] = {"name": "d"}
        accounts = [a, b, c, d]
        filtered = integ.filter_accounts(accounts)
        self.assertEqual(filtered, [a])

    def test_get_deleted_keys(self) -> None:
        a: dict[str, Any] = {"name": "a", "deleteKeys": ["k1", "k2"]}
        b: dict[str, Any] = {"name": "b", "deleteKeys": None}
        c: dict[str, Any] = {"name": "c", "deleteKeys": []}
        accounts = [a, b, c]
        expected_result = {a["name"]: a["deleteKeys"]}
        keys_to_delete = integ.get_deleted_keys(accounts)
        self.assertEqual(keys_to_delete, expected_result)
