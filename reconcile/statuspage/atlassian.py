import logging
import time
from datetime import datetime
from typing import (
    Any,
    Self,
)

import requests
from pydantic import BaseModel
from requests import Response
from sretoolbox.utils import retry

from reconcile.gql_definitions.statuspage.statuspages import StatusPageV1
from reconcile.statuspage.page import (
    StatusComponent,
    StatusMaintenance,
    StatusMaintenanceAnnouncement,
    StatusPage,
)
from reconcile.statuspage.state import ComponentBindingState
from reconcile.statuspage.status import ManualStatusProvider


class AtlassianRawComponent(BaseModel):
    """
    atlassian status page REST schema for component
    """

    id: str
    name: str
    description: str | None
    position: int
    status: str
    automation_email: str | None
    group_id: str | None
    group: bool | None


class AtlassianRawMaintenanceUpdate(BaseModel):
    """
    atlassian status page REST schema for maintenance updates
    """

    body: str


class AtlassianRawMaintenance(BaseModel):
    """
    atlassian status page REST schema for maintenance
    """

    id: str
    name: str
    scheduled_for: str
    scheduled_until: str
    incident_updates: list[AtlassianRawMaintenanceUpdate]
    components: list[AtlassianRawComponent]
    auto_transition_deliver_notifications_at_end: bool | None
    auto_transition_deliver_notifications_at_start: bool | None
    scheduled_remind_prior: bool | None


class AtlassianAPI:
    """
    This API class wraps the statuspageio REST API for basic component operations.
    """

    def __init__(self, page_id: str, api_url: str, token: str):
        self.page_id = page_id
        self.api_url = api_url
        self.token = token
        self.auth_headers = {"Authorization": f"OAuth {self.token}"}

    @retry(max_attempts=10)
    def _do_get(self, url: str, params: dict[str, Any]) -> Response:
        response = requests.get(
            url, params=params, headers=self.auth_headers, timeout=30
        )
        response.raise_for_status()
        return response

    def _list_items(self, url: str) -> list[Any]:
        all_items: list[Any] = []
        page = 1
        per_page = 100
        while True:
            params = {"page": page, "per_page": per_page}
            response = self._do_get(url, params=params)
            items = response.json()
            all_items += items
            if len(items) < per_page:
                break
            page += 1
            # https://developer.statuspage.io/#section/Rate-Limiting
            # Each API token is limited to 1 request / second as measured on a 60 second rolling window
            time.sleep(1)

        return all_items

    def list_components(self) -> list[AtlassianRawComponent]:
        url = f"{self.api_url}/v1/pages/{self.page_id}/components"
        all_components = self._list_items(url)
        return [AtlassianRawComponent(**c) for c in all_components]

    def update_component(self, id: str, data: dict[str, Any]) -> None:
        url = f"{self.api_url}/v1/pages/{self.page_id}/components/{id}"
        requests.patch(
            url, json={"component": data}, headers=self.auth_headers
        ).raise_for_status()

    def create_component(self, data: dict[str, Any]) -> str:
        url = f"{self.api_url}/v1/pages/{self.page_id}/components"
        response = requests.post(
            url, json={"component": data}, headers=self.auth_headers
        )
        response.raise_for_status()
        return response.json()["id"]

    def delete_component(self, id: str) -> None:
        url = f"{self.api_url}/v1/pages/{self.page_id}/components/{id}"
        requests.delete(url, headers=self.auth_headers).raise_for_status()

    def list_scheduled_maintenances(self) -> list[AtlassianRawMaintenance]:
        url = f"{self.api_url}/v1/pages/{self.page_id}/incidents/scheduled"
        all_scheduled_incidents = self._list_items(url)
        return [AtlassianRawMaintenance(**i) for i in all_scheduled_incidents]

    def list_active_maintenances(self) -> list[AtlassianRawMaintenance]:
        url = f"{self.api_url}/v1/pages/{self.page_id}/incidents/active_maintenance"
        all_active_incidents = self._list_items(url)
        return [AtlassianRawMaintenance(**i) for i in all_active_incidents]

    def create_incident(self, data: dict[str, Any]) -> str:
        url = f"{self.api_url}/v1/pages/{self.page_id}/incidents"
        response = requests.post(
            url, json={"incident": data}, headers=self.auth_headers
        )
        response.raise_for_status()
        return response.json()["id"]


class AtlassianStatusPageProvider:
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

    def get_component_by_id(self, id: str) -> StatusComponent | None:
        raw = self.get_raw_component_by_id(id)
        if raw:
            return self._bound_raw_component_to_status_component(raw)
        return None

    def get_raw_component_by_id(self, id: str) -> AtlassianRawComponent | None:
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

    def _raw_component_to_status_component(
        self, raw_component: AtlassianRawComponent, name_override: str | None = None
    ) -> StatusComponent:
        group_name = (
            self._group_id_to_name.get(raw_component.group_id)
            if raw_component.group_id
            else None
        )
        return StatusComponent(
            name=name_override or raw_component.name,
            display_name=raw_component.name,
            description=raw_component.description,
            group_name=group_name,
            status_provider_configs=[
                ManualStatusProvider(
                    component_status=raw_component.status,
                )
            ],
        )

    def _bound_raw_component_to_status_component(
        self, raw_component: AtlassianRawComponent
    ) -> StatusComponent | None:
        bound_component_name = self._binding_state.get_name_for_component_id(
            raw_component.id
        )
        if bound_component_name:
            return self._raw_component_to_status_component(
                raw_component, name_override=bound_component_name
            )
        return None

    def lookup_component(
        self, desired_component: StatusComponent
    ) -> tuple[AtlassianRawComponent | None, bool]:
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
        self, desired: StatusComponent, current: AtlassianRawComponent | None
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
        active_maintenance_affecting_component = [
            m
            for m in self.active_maintenances
            if desired.display_name in [c.name for c in m.components]
        ]
        status_update_required = (
            desired_component_status is not None
            and (not current or desired_component_status != current.status)
            and not active_maintenance_affecting_component
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

        # validate the component and check if the current state needs to be updated
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
            active_maintenance_affecting_component = [
                m
                for m in self.active_maintenances
                if desired.display_name in [c.name for c in m.components]
            ]
            if not active_maintenance_affecting_component:
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

    def _raw_maintenance_to_status_maintenance(
        self,
        raw_maintenance: AtlassianRawMaintenance,
        name_override: str | None = None,
    ) -> StatusMaintenance:
        return StatusMaintenance(
            name=name_override or raw_maintenance.name,
            message=raw_maintenance.incident_updates[0].body,
            schedule_start=datetime.fromisoformat(raw_maintenance.scheduled_for),
            schedule_end=datetime.fromisoformat(raw_maintenance.scheduled_until),
            components=[
                self._raw_component_to_status_component(c)
                for c in raw_maintenance.components
            ],
            announcements=StatusMaintenanceAnnouncement(
                remind_subscribers=raw_maintenance.scheduled_remind_prior,
                notify_subscribers_on_start=raw_maintenance.auto_transition_deliver_notifications_at_start,
                notify_subscribers_on_completion=raw_maintenance.auto_transition_deliver_notifications_at_end,
            ),
        )

    @classmethod
    def init_from_page(
        cls,
        page: StatusPageV1,
        token: str,
        component_binding_state: ComponentBindingState,
    ) -> Self:
        """
        Initializes the provider for atlassian status page.
        """
        return cls(
            page_name=page.name,
            api=AtlassianAPI(
                page_id=page.page_id,
                api_url=page.api_url,
                token=token,
            ),
            component_binding_state=component_binding_state,
        )

    @property
    def scheduled_maintenances(self) -> list[StatusMaintenance]:
        return [
            self._raw_maintenance_to_status_maintenance(m)
            for m in self._api.list_scheduled_maintenances()
        ]

    @property
    def active_maintenances(self) -> list[StatusMaintenance]:
        return [
            self._raw_maintenance_to_status_maintenance(m)
            for m in self._api.list_active_maintenances()
        ]

    def create_maintenance(self, maintenance: StatusMaintenance) -> None:
        component_ids: list[str] = []
        for sc in maintenance.components:
            current_component, _ = self.lookup_component(sc)
            if current_component:
                component_ids.append(current_component.id)
        data = {
            "name": maintenance.name,
            "status": "scheduled",
            "scheduled_for": maintenance.schedule_start.isoformat(),
            "scheduled_until": maintenance.schedule_end.isoformat(),
            "body": maintenance.message,
            "scheduled_remind_prior": maintenance.announcements.remind_subscribers,
            "scheduled_auto_transition": True,
            "scheduled_auto_in_progress": True,
            "scheduled_auto_completed": True,
            "component_ids": component_ids,
            "auto_transition_to_maintenance_state": True,
            "auto_transition_to_operational_state": True,
            "auto_transition_deliver_notifications_at_start": maintenance.announcements.notify_subscribers_on_start,
            "auto_transition_deliver_notifications_at_end": maintenance.announcements.notify_subscribers_on_completion,
        }
        incident_id = self._api.create_incident(data)
        self._bind_component(
            dry_run=False,
            component_name=maintenance.name,
            component_id=incident_id,
        )
