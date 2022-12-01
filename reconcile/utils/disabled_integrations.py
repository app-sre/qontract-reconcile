from collections.abc import Mapping
from typing import (
    Any,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)


class IntegrationDisable(Protocol):
    integrations: Optional[list[str]]


@runtime_checkable
class Disable(Protocol):
    @property
    def disable(self) -> Optional[IntegrationDisable]:
        pass


def disabled_integrations(
    disable_obj: Optional[Union[Mapping[str, Any], Disable]]
) -> list[str]:
    """Returns all disabled integrations"""
    if not disable_obj:
        return []

    if isinstance(disable_obj, Disable):
        if disable_obj.disable:
            return disable_obj.disable.integrations or []
    else:
        disable = disable_obj.get("disable")
        if disable:
            return disable.get("integrations") or []
    return []


def integration_is_enabled(
    integration: str, disable_obj: Optional[Union[Mapping[str, Any], Disable]]
) -> bool:
    """A convenient method to check whether an integration is enabled or not."""
    return integration not in disabled_integrations(disable_obj)
