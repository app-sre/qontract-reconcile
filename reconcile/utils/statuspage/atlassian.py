import logging
from collections.abc import Iterable
from typing import (
    Any,
    Optional,
)

import statuspageio  # type: ignore
from pydantic import BaseModel

from reconcile.utils.statuspage.models import (
    StatusComponent,
    StatusPage,
    StatusPageProvider,
)

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


class AtlassianStatusPage(StatusPageProvider):

    page_id: str
    api_url: str
    token: str

    components_by_id: dict[str, AtlassianComponent] = {}
    components_by_displayname: dict[str, AtlassianComponent] = {}
    group_name_to_id: dict[str, str] = {}

    def rebuild_state(self):
        components = self._fetch_components()
        self.components_by_id = {c.id: c for c in components}
        self.components_by_displayname = {c.name: c for c in components}
        self.group_name_to_id = {g.name: g.id for g in components if g.group}

    def component_ids(self) -> Iterable[str]:
        return self.components_by_id.keys()

    def _find_component(
        self, component: StatusComponent
    ) -> Optional[AtlassianComponent]:
        if component.component_id and component.component_id in self.components_by_id:
            return self.components_by_id.get(component.component_id)
        else:
            return self.components_by_displayname.get(component.display_name)

    def apply_component(self, dry_run: bool, desired: StatusComponent) -> Optional[str]:
        current = self._find_component(desired)

        desired_component_status = desired.desired_component_status()
        status_update_required = desired_component_status and (
            not current or desired_component_status != current.status
        )

        if (
            current
            and desired.display_name == current.name
            and desired.description == current.description
            and desired.group_name == current.group_name
            and not status_update_required
        ):
            return current.id

        # precheck - does the desired group exists?
        group_id = None
        if desired.group_name:
            group_id = self.group_name_to_id.get(desired.group_name, None)
            if not group_id:
                raise ValueError(
                    f"Group {desired.group_name} referenced "
                    f"by {desired.name} does not exist"
                )

        # Special handling if a component needs to be moved out of any grouping
        # We would need to use the component_group endpoint but for now let's
        # just raise this as an error because of lazyness へ‿(ツ)‿ㄏ
        if current and current.group_name and not desired.group_name:
            raise ValueError(
                f"Remove grouping from the component "
                f"{desired.group_name} is currently unsupported"
            )

        component_update = {
            "name": desired.display_name,
            "description": desired.description,
        }
        if group_id:
            component_update["group_id"] = group_id

        if status_update_required:
            component_update["status"] = desired_component_status

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
            self.rebuild_state()

    def _fetch_components(self) -> list[AtlassianComponent]:
        raw_components = self._client().components.list()
        group_ids_to_name = {g.id: g.name for g in raw_components if g.group}
        return [
            AtlassianComponent(
                **c.toDict(), group_name=group_ids_to_name.get(c.group_id, None)
            )
            for c in raw_components
        ]

    def _client(self):
        return statuspageio.Client(
            api_key=self.token, page_id=self.page_id, organization_id="unset"
        )


def load_provider(page: StatusPage) -> StatusPageProvider:
    provider = AtlassianStatusPage(
        page_id=page.page_id,
        api_url=page.api_url,
        token=page.credentials.get("token"),
    )
    provider.rebuild_state()
    return provider
