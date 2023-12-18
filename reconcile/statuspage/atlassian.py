import logging
from typing import (
    Any,
    Optional,
    Protocol,
)

import statuspageio  # type: ignore
from pydantic import BaseModel

from reconcile.gql_definitions.statuspage.statuspages import StatusPageV1
from reconcile.statuspage.page import (
    StatusComponent,
    StatusPage,
    StatusPageProvider,
)
from reconcile.statuspage.state import ComponentBindingState
from reconcile.statuspage.status import ManualStatusProvider

PROVIDER_NAME = "atlassian"


class AtlassianRawComponent(BaseModel):
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


class AtlassianAPI(Protocol):
    def list_components(self) -> list[AtlassianRawComponent]: ...

    def update_component(self, id: str, data: dict[str, Any]) -> None: ...

    def create_component(self, data: dict[str, Any]) -> str: ...

    def delete_component(self, id: str) -> None: ...


class LegacyLibAtlassianAPI:
    """
    This API class wraps the statuspageio python library for basic component operations.
    This class is named Legacy for a couple reasons:
    * the underlying library is not maintained anymore
    * the library has no type annotated
    * the library does not support pagination which becomes important for this API
    Therefore this lib will be replaced by a think wrapper based on uplink in an upcoming PR.
    """

    def __init__(self, page_id: str, api_url: str, token: str):
        self.page_id = page_id
        self.api_url = api_url
        self.token = token
        self._client = statuspageio.Client(
            api_key=self.token, page_id=self.page_id, organization_id="unset"
        )

    def list_components(self) -> list[AtlassianRawComponent]:
        return [
            AtlassianRawComponent(
                **c.toDict(),
            )
            for c in self._client.components.list()
        ]

    def update_component(self, id: str, data: dict[str, Any]) -> None:
        self._client.components.update(id, **data)

    def create_component(self, data: dict[str, Any]) -> str:
        result = self._client.components.create(**data)
        return result["id"]

    def delete_component(self, id: str) -> None:
        self._client.components.delete(id)


class AtlassianStatusPageProvider(StatusPageProvider):
    """
    The provider implements CRUD operations for Atlassian status pages.
    It also takes care of a mixed set of components on a page, where some
    components are managed by app-interface and some are managed manually
    by various teams. The term `bound` used throughout the code refers to
    components that are managed by app-interface. The binding status is
    managed by the injected `ComponentBindingState` instance and persists
    the binding information (what app-interface component name is bound to
    what status page component id).
    """

    def __init__(
        self,
        page_name: str,
        api: AtlassianAPI,
        component_binding_state: ComponentBindingState,
    ):
        self.page_name = page_name
        self._api = api
        self._binding_state = component_binding_state

        # component cache
        self._components: list[AtlassianRawComponent] = []
        self._components_by_id: dict[str, AtlassianRawComponent] = {}
        self._components_by_displayname: dict[str, AtlassianRawComponent] = {}
        self._group_name_to_id: dict[str, str] = {}
        self._group_id_to_name: dict[str, str] = {}
        self._build_component_cache()

    def _build_component_cache(self):
        self._components = self._api.list_components()
        self._components_by_id = {c.id: c for c in self._components}
        self._components_by_displayname = {c.name: c for c in self._components}
        self._group_name_to_id = {g.name: g.id for g in self._components if g.group}
        self._group_id_to_name = {g.id: g.name for g in self._components if g.group}

    def get_component_by_id(self, id: str) -> Optional[StatusComponent]:
        raw = self.get_raw_component_by_id(id)
        if raw:
            return self._bound_raw_component_to_status_component(raw)
        return None

    def get_raw_component_by_id(self, id: str) -> Optional[AtlassianRawComponent]:
        return self._components_by_id.get(id)

    def get_current_page(self) -> StatusPage:
        """
        Builds a StatusPage instance from the current state of the page. This
        way the current state of the page can be compared to the desired state
        of the page coming from GQL.
        """
        components = [
            self._bound_raw_component_to_status_component(c) for c in self._components
        ]
        return StatusPage(
            name=self.page_name,
            components=[c for c in components if c is not None],
        )

    def _bound_raw_component_to_status_component(
        self, raw_component: AtlassianRawComponent
    ) -> Optional[StatusComponent]:
        bound_component_name = self._binding_state.get_name_for_component_id(
            raw_component.id
        )
        if bound_component_name:
            group_name = (
                self._group_id_to_name.get(raw_component.group_id)
                if raw_component.group_id
                else None
            )
            return StatusComponent(
                name=bound_component_name,
                display_name=raw_component.name,
                description=raw_component.description,
                group_name=group_name,
                status_provider_configs=[
                    ManualStatusProvider(
                        component_status=raw_component.status,
                    )
                ],
            )
        return None

    def lookup_component(
        self, desired_component: StatusComponent
    ) -> tuple[Optional[AtlassianRawComponent], bool]:
        """
        Finds the component on the page that matches the desired component. This
        is either done explicitely by using binding information if available or
        by using the display name of the desired component to find a matching
        component on the page. This way, this provider offers adoption logic
        for existing components on the page that are not yes bound to app-interface.
        """
        component_id = self._binding_state.get_id_for_component_name(
            desired_component.name
        )
        component = None
        bound = True
        if component_id:
            component = self.get_raw_component_by_id(component_id)

        if component is None:
            bound = False
            # either the component name is not bound to an ID or for whatever
            # reason or the component is not found on the page anymore
            component = self._components_by_displayname.get(
                desired_component.display_name
            )
            if component and self._binding_state.get_name_for_component_id(
                component.id
            ):
                # this component is already bound to a different component
                # in app-interface. we are protecting this binding here by
                # not allowing this component to be found via display name
                component = None

        return component, bound

    def should_apply(
        self, desired: StatusComponent, current: Optional[AtlassianRawComponent]
    ) -> bool:
        """
        Verifies if the desired component should be applied to the status page
        when compared to the current state of the component on the page.
        """
        current_group_name = (
            self._group_id_to_name.get(current.group_id)
            if current and current.group_id
            else None
        )

        # check if group exists
        group_id = None
        if desired.group_name:
            group_id = self._group_name_to_id.get(desired.group_name, None)
            if not group_id:
                raise ValueError(
                    f"Group {desired.group_name} referenced "
                    f"by {desired.name} does not exist"
                )

        # Special handling if a component needs to be moved out of any grouping.
        # We would need to use the component_group endpoint but for not lets
        # ignore this situation.
        if current and current_group_name and not desired.group_name:
            raise ValueError(
                f"Remove grouping from the component "
                f"{desired.group_name} is currently unsupported"
            )

        # component status
        desired_component_status = desired.desired_component_status()
        status_update_required = desired_component_status is not None and (
            not current or desired_component_status != current.status
        )

        # shortcut execution if there is nothing to do
        update_required = (
            current is None
            or desired.display_name != current.name
            or desired.description != current.description
            or desired.group_name != current_group_name
            or status_update_required
        )
        return update_required

    def apply_component(self, dry_run: bool, desired: StatusComponent) -> None:
        current_component, bound = self.lookup_component(desired)

        # if the component is not yet bound to a statuspage component, bind it now
        if current_component and not bound:
            self._bind_component(
                dry_run=dry_run,
                component_name=desired.name,
                component_id=current_component.id,
            )

        # validte the component and check if the current state needs to be updated
        needs_update = self.should_apply(desired, current_component)
        if not needs_update:
            return

        # calculate update
        component_update = {
            "name": desired.display_name,
            "description": desired.description,
        }

        # resolve group
        group_id = (
            self._group_name_to_id.get(desired.group_name, None)
            if desired.group_name
            else None
        )
        if group_id:
            component_update["group_id"] = group_id

        # resolve status
        desired_component_status = desired.desired_component_status()
        if desired_component_status:
            component_update["status"] = desired_component_status

        if current_component:
            logging.info(f"update component {desired.name}: {component_update}")
            if not dry_run:
                self._api.update_component(current_component.id, component_update)
        else:
            logging.info(f"create component {desired.name}: {component_update}")
            if not dry_run:
                component_id = self._api.create_component(component_update)
                self._bind_component(
                    dry_run=dry_run,
                    component_name=desired.name,
                    component_id=component_id,
                )

    def delete_component(self, dry_run: bool, component_name: str) -> None:
        component_id = self._binding_state.get_id_for_component_name(component_name)
        if component_id:
            if not dry_run:
                self._api.delete_component(component_id)
                self._binding_state.forget_component(component_name)
                self._build_component_cache()
        else:
            logging.warning(
                f"can't delete component {component_name} because it is not "
                f"bound to any component on page {self.page_name}"
            )

    def has_component_binding_for(self, component_name: str) -> bool:
        return self._binding_state.get_id_for_component_name(component_name) is not None

    def _bind_component(
        self,
        dry_run: bool,
        component_name: str,
        component_id: str,
    ) -> None:
        logging.info(
            f"bind component {component_name} to ID {component_id} "
            f"on page {self.page_name}"
        )
        if not dry_run:
            self._binding_state.bind_component(component_name, component_id)


def init_provider_for_page(
    page: StatusPageV1,
    token: str,
    component_binding_state: ComponentBindingState,
) -> AtlassianStatusPageProvider:
    """
    Initializes the provider for atlassian status page.
    """
    return AtlassianStatusPageProvider(
        page_name=page.name,
        api=LegacyLibAtlassianAPI(
            page_id=page.page_id,
            api_url=page.api_url,
            token=token,
        ),
        component_binding_state=component_binding_state,
    )
