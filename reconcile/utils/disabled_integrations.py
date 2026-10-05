from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


class HasIntegrations(Protocol):
    integrations: list[str] | None


@runtime_checkable
class HasDisableIntegrations(Protocol):
    @property
    def disable(self) -> HasIntegrations | None:
        pass


def disabled_integrations(
    disable_obj: Mapping[str, Any] | HasDisableIntegrations | None,
) -> list[str]:
    """Returns all disabled integrations"""
    if not disable_obj:
        return []

    if isinstance(disable_obj, HasDisableIntegrations):
        if disable_obj.disable:
            return disable_obj.disable.integrations or []
    else:
        disable = disable_obj.get("disable")
        if disable:
            return disable.get("integrations") or []
    return []


def integration_is_enabled(
    integration: str,
    disable_obj: Mapping[str, Any] | HasDisableIntegrations | None,
) -> bool:
    """A convenient method to check whether an integration is enabled or not."""
    return integration not in disabled_integrations(disable_obj)


# AWS SSO rover groups only: honor legacy and -api names in account.disable.integrations.
_LDAP_GROUPS_AWS_DISABLE_NAMES = frozenset({"ldap-groups", "ldap-groups-api"})


def ldap_groups_aws_integration_enabled(
    disable_obj: Mapping[str, Any] | HasDisableIntegrations | None,
) -> bool:
    disabled = set(disabled_integrations(disable_obj))
    return not disabled.intersection(_LDAP_GROUPS_AWS_DISABLE_NAMES)
