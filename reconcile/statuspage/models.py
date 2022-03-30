from abc import abstractmethod
import logging
from typing import Callable, Iterable, Optional
from pydantic import Field, BaseModel
from pydantic.networks import HttpUrl
from reconcile.utils.state import State

from reconcile.utils.vaultsecretref import VaultSecretRef


LOG = logging.getLogger(__name__)


class StatusComponent(BaseModel):
    """
    app-interface schema dependencies/status-page-component-1
    """

    name: str
    display_name: str = Field(..., alias="displayName")
    description: Optional[str]
    group_name: Optional[str] = Field(..., alias="groupName")
    component_id: Optional[str]


class StatusPageProvider(BaseModel):
    """
    Provider specific status page reconcile implementation is implemented
    as a subclass of `StatusPageProvider`
    """

    @abstractmethod
    def component_ids(self) -> Iterable[str]:
        return []

    @abstractmethod
    def apply_component(self, dry_run: bool, desired: StatusComponent) -> Optional[str]:
        return None

    @abstractmethod
    def delete_component(self, dry_run: bool, id: str) -> None:
        return None

    @abstractmethod
    def update_component_status(self, dry_run: bool, id: str, status: str) -> None:
        return None


class StatusPage(BaseModel):
    """
    app-interface schema dependencies/status-page-1
    """

    name: str
    page_id: str = Field(..., alias="pageId")
    api_url: HttpUrl = Field(..., alias="apiUrl")
    credentials: VaultSecretRef
    components: list[StatusComponent]
    provider: str

    def get_page_provider(self) -> StatusPageProvider:
        loader = PROVIDER_LOADERS.get(self.provider)
        if loader:
            return loader(self)
        else:
            raise ValueError(f"provider {self.provider} is not supported")

    def get_component_by_name(self, name) -> Optional[StatusComponent]:
        return next(
            filter(lambda c: c.name == name, self.components), None  # type: ignore
        )

    def update_component_status(
        self, dry_run: bool, component_name: str, component_status: str, state: State
    ) -> None:
        component_id = state.get(component_name)
        if component_id:
            page_provider = self.get_page_provider()
            page_provider.update_component_status(
                dry_run, component_id, component_status
            )
        else:
            raise ValueError(f"component {component_name} unknown")

    def reconcile(self, dry_run: bool, state: State):
        name_to_id_state = state.get_all("")
        page_provider = self.get_page_provider()

        # restore component ids from state
        for desired in self.components:
            desired.component_id = name_to_id_state.get(desired.name)

        # delete
        id_to_name_state = {v: k for k, v in name_to_id_state.items()}
        desired_component_names = [c.name for c in self.components]
        for current_id in page_provider.component_ids():
            # if the component is known to the state management and if it is
            # not known to the desired state, it was once managed by this
            # integration but was delete from app-interface -> delete from page
            name_for_current_component = id_to_name_state.get(current_id)
            if (
                name_for_current_component
                and name_for_current_component not in desired_component_names
            ):
                LOG.info(
                    f"delete component {name_for_current_component} "
                    f"from page {self.name}"
                )
                page_provider.delete_component(dry_run, current_id)
                if not dry_run:
                    state.rm(name_for_current_component)

        # create and update
        for desired in self.components:
            component_id = page_provider.apply_component(dry_run, desired)
            if component_id and desired.component_id != component_id:
                self._bind_component(dry_run, desired, component_id, state)

    def _bind_component(
        self, dry_run: bool, component: StatusComponent, component_id: str, state: State
    ) -> None:
        LOG.info(
            f"bind component {component.name} to ID {component_id} "
            f"on page {self.name}"
        )
        if not dry_run:
            state.add(component.name, component_id, force=True)
            component.component_id = component_id


ProviderLoader = Callable[[StatusPage], StatusPageProvider]
PROVIDER_LOADERS: dict[str, ProviderLoader] = {}


def register_provider(provider: str, loader: ProviderLoader) -> None:
    PROVIDER_LOADERS[provider] = loader
