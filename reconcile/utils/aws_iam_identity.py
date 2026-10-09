"""Identity and provisioning prerequisites for IAM membership consumers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable


class IamUserInventory(Protocol):
    def _get_account_users(self, account: str) -> list[str]: ...


class MissingIamUsersError(ValueError):
    """A membership consumer cannot provision missing IAM identities."""


def require_iam_users(
    aws_api: IamUserInventory, *, account_name: str, usernames: Iterable[str]
) -> None:
    """Fail before mutations when required IAM users have not been provisioned."""
    if requested := set(usernames):
        if missing := requested - set(aws_api._get_account_users(account_name)):
            raise MissingIamUsersError(
                f"IAM users are not provisioned in {account_name}: {sorted(missing)}. Retain explicit identity/provisioning requirements before enabling LDAP-only membership."
            )
