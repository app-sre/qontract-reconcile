from abc import abstractmethod
import logging
from typing import Optional, Any
from collections.abc import Iterable
import sys

from pydantic import BaseModel, Field
from pydantic.networks import HttpUrl
import statuspageio  # type: ignore

from reconcile import queries
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import State
from reconcile.utils.vaultsecretref import VaultSecretRef


QONTRACT_INTEGRATION = "status-page-components"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


LOG = logging.getLogger(__name__)


class AtlassianComponent(BaseModel):
    """
    atlassian status page REST schema for component
    """

    id: str
    name: str
    description: Optional[str]
    position: int
    status: str
    automation_email: Optional[str]
    group_id: Optional[str]
    group: Optional[bool]
    group_name: Optional[str]


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
    def apply_component(self, dry_run: bool,
                        desired: StatusComponent) -> Optional[str]:
        return None

    @abstractmethod
    def delete_component(self, dry_run: bool, id: str):
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
        if self.provider == "atlassian":
            return AtlassianStatusPage(page_id=self.page_id,
                                       api_url=self.api_url,
                                       token=self.credentials.get("token"))
        else:
            raise ValueError(f"provider {self.provider} is not supported")

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
            if (name_for_current_component and
               name_for_current_component not in desired_component_names):
                LOG.info(f"delete component {name_for_current_component} "
                         f"from page {self.name}")
                page_provider.delete_component(dry_run, current_id)
                if not dry_run:
                    state.rm(name_for_current_component)

        # create and update
        for desired in self.components:
            component_id = page_provider.apply_component(dry_run, desired)
            if component_id and desired.component_id != component_id:
                self._bind_component(dry_run, desired, component_id, state)

    def _bind_component(self, dry_run: bool,
                        component: StatusComponent, component_id: str,
                        state: State) -> None:
        LOG.info(f"bind component {component.name} to ID {component_id} "
                 f"on page {self.name}")
        if not dry_run:
            state.add(component.name, component_id, force=True)
            component.component_id = component_id


class AtlassianStatusPage(StatusPageProvider):

    page_id: str
    api_url: str
    token: str

    components_by_id: dict[str, AtlassianComponent] = {}
    components_by_displayname: dict[str, AtlassianComponent] = {}
    group_name_to_id: dict[str, str] = {}

    def __init__(self, **data):
        super().__init__(**data)
        self._rebuild_state()

    def _rebuild_state(self):
        components = self._fetch_components()
        self.components_by_id = {c.id: c for c in components}
        self.components_by_displayname = {c.name: c for c in components}
        self.group_name_to_id = {g.name: g.id for g in components if g.group}

    def component_ids(self) -> Iterable[str]:
        return self.components_by_id.keys()

    def _find_component(self,
                        component: StatusComponent
                        ) -> Optional[AtlassianComponent]:
        if component.component_id \
           and component.component_id in self.components_by_id:
            return self.components_by_id.get(component.component_id)
        else:
            return self.components_by_displayname.get(component.display_name)

    def apply_component(self, dry_run: bool,
                        desired: StatusComponent) -> Optional[str]:
        current = self._find_component(desired)
        if current \
           and desired.display_name == current.name \
           and desired.description == current.description \
           and desired.group_name == current.group_name:
            # todo logging
            return current.id

        # precheck - does the desired group exists?
        group_id = None
        if desired.group_name:
            group_id = self.group_name_to_id.get(desired.group_name, None)
            if not group_id:
                raise ValueError(f"Group {desired.group_name} referenced "
                                 f"by {desired.name} does not exist")

        # Special handling if a component needs to be moved out of any grouping
        # We would need to use the component_group endpoint but for now let's
        # just raise this as an error because of lazyness へ‿(ツ)‿ㄏ
        if current and current.group_name and not desired.group_name:
            raise ValueError(f"Remove grouping from the component "
                             f"{desired.group_name} is currently unsupported")

        component_update = dict(
            name=desired.display_name,
            description=desired.description
        )
        if group_id:
            component_update["group_id"] = group_id

        if current:
            LOG.info(f"update component {desired.name}: {component_update}")
            if not dry_run:
                self._update_component(current.id, component_update)
            return current.id
        else:
            LOG.info(f"create component {desired.name}: {component_update}")
            if not dry_run:
                return self._create_component(component_update)
            else:
                return None

    def _update_component(self, id: str, data: dict[str, Any]) -> None:
        self._client().components.update(id, **data)

    def _create_component(self, data: dict[str, Any]) -> Optional[str]:
        result = self._client().components.create(**data)
        return result.get("id")

    def delete_component(self, dry_run: bool, id: str) -> None:
        if not dry_run:
            self._client().components.delete(id)
            self._rebuild_state()

    def _fetch_components(self) -> list[AtlassianComponent]:
        raw_components = self._client().components.list()
        group_ids_to_name = {g.id: g.name for g in raw_components if g.group}
        return [
            AtlassianComponent(
                **c.toDict(),
                group_name=group_ids_to_name.get(c.group_id, None)
            )
            for c in raw_components
        ]

    def _client(self):
        return statuspageio.Client(api_key=self.token,
                                   page_id=self.page_id,
                                   organization_id="unset")


def fetch_pages() -> list[StatusPage]:
    return [StatusPage(**p) for p in queries.get_status_pages()]


def get_state() -> State:
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    return State(integration=QONTRACT_INTEGRATION,
                 accounts=accounts,
                 settings=settings)


def run(dry_run: bool = False):
    state = get_state()
    status_pages = fetch_pages()

    page_reconcile_error_occured = False
    for page in status_pages:
        try:
            page.reconcile(dry_run, state)
        except Exception:
            LOG.exception(f"failed to reconcile statuspage {page.name}")
            page_reconcile_error_occured = True

    if page_reconcile_error_occured:
        sys.exit(1)
