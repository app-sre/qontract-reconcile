from collections.abc import Mapping
from typing import (
    Any,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)


class HasIntegrations(Protocol):
    integrations: Optional[list[str]]


@runtime_checkable
class HasDisableIntegrations(Protocol):
    @property
    def disable(self) -> Optional[HasIntegrations]:
        pass


def disabled_integrations(
    disable_obj: Optional[Union[Mapping[str, Any], HasDisableIntegrations]],
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
    disable_obj: Optional[Union[Mapping[str, Any], HasDisableIntegrations]],
) -> bool:
    """A convenient method to check whether an integration is enabled or not."""
    return integration not in disabled_integrations(disable_obj)
