from typing import (
    Optional,
    Protocol,
)

from reconcile.utils.state import State

"""
This module manages the binding state of components in the desired state
and their representation on an actual status page.

This state management is required to map component identities between app-interface
and the status page provider.
"""


class ComponentBindingState(Protocol):
    def get_id_for_component_name(self, component_name: str) -> Optional[str]:
        ...

    def get_name_for_component_id(self, component_id: str) -> Optional[str]:
        ...

    def bind_component(self, component_name: str, component_id: str) -> None:
        ...

    def forget_component(self, component_name: str) -> None:
        ...


class S3ComponentBindingState(ComponentBindingState):
    def __init__(self, state: State):
        self.state = state
        self._update_cache()

    def _update_cache(self) -> None:
        self.name_to_id_cache: dict[str, str] = self.state.get_all("")
        self.id_to_name_cache: dict[str, str] = {
            v: k for k, v in self.name_to_id_cache.items()
        }

    def get_id_for_component_name(self, component_name: str) -> Optional[str]:
        return self.name_to_id_cache.get(component_name)

    def get_name_for_component_id(self, component_id: str) -> Optional[str]:
        return self.id_to_name_cache.get(component_id)

    def bind_component(self, component_name: str, component_id: str) -> None:
        self.state.add(component_name, component_id, force=True)
        self._update_cache()

    def forget_component(self, component_name: str) -> None:
        self.state.rm(component_name)
