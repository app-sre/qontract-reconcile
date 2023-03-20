from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel

from reconcile.gql_definitions.statuspage.statuspages import (
    StatusPageComponentV1,
    StatusPageV1,
)
from reconcile.statuspage.state import ComponentBindingState
from reconcile.statuspage.status import (
    StatusProvider,
    build_status_provider_config,
)


def build_status_page_component(component: StatusPageComponentV1) -> "StatusComponent":
    status_configs = [
        build_status_provider_config(cfg) for cfg in component.status_config or []
    ]
    return StatusComponent(
        name=component.name,
        display_name=component.display_name,
        description=component.description,
        group_name=component.group_name,
        status_provider_configs=[c for c in status_configs if c is not None],
    )


class StatusComponent(BaseModel):
    """
    Represents a status page component from the desired state.
    """

    name: str
    display_name: str
    description: Optional[str]
    group_name: Optional[str]
    status_provider_configs: list[StatusProvider]
    """
    Status provider configs hold different ways for a component to determine its status
    """

    def status_management_enabled(self) -> bool:
        """
        Determines if this component has any status configurations available for
        it to be able to manage its status.
        """
        return bool(self.status_provider_configs)

    def desired_component_status(self) -> Optional[str]:
        if self.status_management_enabled():
            for provider in self.status_provider_configs:
                status = provider.get_status()
                if status:
                    return status
            return "operational"
        return None

    class Config:
        arbitrary_types_allowed = True


class StatusPageProvider(ABC):
    """
    Provider specific status page reconcile implementation.
    """

    @abstractmethod
    def get_current_page(self) -> "StatusPage":
        ...

    @abstractmethod
    def apply_component(self, dry_run: bool, desired: StatusComponent) -> None:
        ...

    @abstractmethod
    def delete_component(self, dry_run: bool, component_name: str) -> None:
        ...


def build_status_page(
    page: StatusPageV1,
) -> "StatusPage":
    """
    Translate a desired state status page into a status page object.
    """
    return StatusPage(
        name=page.name,
        components=[
            build_status_page_component(component=c) for c in page.components or []
        ],
    )


def init_provider_for_page(
    page: StatusPageV1,
    token: str,
    component_binding_state: ComponentBindingState,
) -> StatusPageProvider:
    """
    Initialize a status page provider for a given status page.
    """
    if page.provider in _PROVIDERS:
        return _PROVIDERS[page.provider](page, token, component_binding_state)
    raise ValueError(f"provider {page.provider} is not supported")


class StatusPage(BaseModel):
    """
    Represents the desired state of a status page and its components.
    """

    name: str
    """
    The name of the status page.
    """

    components: list[StatusComponent]
    """
    The desired components of the status page are represented in this list.
    Important note: the actual status page might have more components than
    this desired state does. People can still manage components manually.
    """


ProviderInitializer = Callable[
    [StatusPageV1, str, ComponentBindingState], StatusPageProvider
]

_PROVIDERS: dict[str, ProviderInitializer] = {}


def register_provider(provider: str, provider_init: ProviderInitializer) -> None:
    _PROVIDERS[provider] = provider_init
