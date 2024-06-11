from collections.abc import Mapping
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)


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
