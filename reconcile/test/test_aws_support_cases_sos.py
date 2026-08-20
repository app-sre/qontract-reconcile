from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest import TestCase

import reconcile.aws_support_cases_sos as integ

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


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


def test_run_scopes_get_users_keys_to_accounts_with_candidate_keys(
    mocker: MockerFixture,
) -> None:
    account: dict[str, Any] = {
        "name": "acct-a",
        "premiumSupport": True,
        "deleteKeys": None,
        "path": "/x",
    }
    mocker.patch(
        "reconcile.aws_support_cases_sos.queries.get_aws_accounts",
        return_value=[account],
    )
    mocker.patch(
        "reconcile.aws_support_cases_sos.queries.get_app_interface_settings",
        return_value={},
    )
    mocker.patch("reconcile.aws_support_cases_sos.act")

    fake_case = {
        "recentCommunications": {
            "communications": [
                {
                    "body": "We have become aware that the AWS Access Key "
                    "AKIA123 was leaked"
                }
            ]
        }
    }
    mock_aws = mocker.MagicMock()
    mock_aws.get_support_cases.return_value = {"acct-a": [fake_case]}
    mock_aws.get_users_keys.return_value = {"acct-a": {"someuser": ["AKIA123"]}}
    mock_aws.__enter__.return_value = mock_aws
    mock_aws.__exit__.return_value = False
    mocker.patch("reconcile.aws_support_cases_sos.AWSApi", return_value=mock_aws)

    integ.run(dry_run=True)

    mock_aws.get_users_keys.assert_called_once_with({"acct-a"})


def test_run_skips_get_users_keys_when_no_candidate_keys(
    mocker: MockerFixture,
) -> None:
    account: dict[str, Any] = {
        "name": "acct-a",
        "premiumSupport": True,
        "deleteKeys": None,
        "path": "/x",
    }
    mocker.patch(
        "reconcile.aws_support_cases_sos.queries.get_aws_accounts",
        return_value=[account],
    )
    mocker.patch(
        "reconcile.aws_support_cases_sos.queries.get_app_interface_settings",
        return_value={},
    )
    mocker.patch("reconcile.aws_support_cases_sos.act")

    mock_aws = mocker.MagicMock()
    mock_aws.get_support_cases.return_value = {"acct-a": []}
    mock_aws.__enter__.return_value = mock_aws
    mock_aws.__exit__.return_value = False
    mocker.patch("reconcile.aws_support_cases_sos.AWSApi", return_value=mock_aws)

    integ.run(dry_run=True)

    mock_aws.get_users_keys.assert_not_called()
