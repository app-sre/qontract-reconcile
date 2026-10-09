from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.utils.aws_iam_identity import (
    MissingIamUsersError,
    require_iam_users,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_iam_inventory_guard_accepts_provisioned_users(mocker: MockerFixture) -> None:
    inventory = mocker.Mock()
    inventory._get_account_users.return_value = ["alice", "bob"]
    require_iam_users(inventory, account_name="account", usernames=["alice"])
    inventory._get_account_users.assert_called_once_with("account")


def test_iam_inventory_guard_rejects_missing_users(mocker: MockerFixture) -> None:
    inventory = mocker.Mock()
    inventory._get_account_users.return_value = ["alice"]
    with pytest.raises(MissingIamUsersError, match="bob"):
        require_iam_users(inventory, account_name="account", usernames=["alice", "bob"])


def test_empty_membership_does_not_require_iam_inventory(mocker: MockerFixture) -> None:
    inventory = mocker.Mock()
    require_iam_users(inventory, account_name="account", usernames=[])
    inventory._get_account_users.assert_not_called()
