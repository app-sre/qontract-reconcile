from typing import Optional, Self

from pydantic import BaseModel

from reconcile.gql_definitions.statuspage.statuspages import (
    MaintenanceV1,
    StatusPageComponentV1,
    StatusPageV1,
)
from reconcile.statuspage.status import (
    StatusProvider,
    build_status_provider_config,
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

    @classmethod
    def init_from_page_component(cls, component: StatusPageComponentV1) -> Self:
        status_configs = [
            build_status_provider_config(cfg) for cfg in component.status_config or []
        ]
        return cls(
            name=component.name,
            display_name=component.display_name,
            description=component.description,
            group_name=component.group_name,
            status_provider_configs=[c for c in status_configs if c is not None],
        )


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

    @classmethod
    def init_from_page(
        cls,
        page: StatusPageV1,
    ) -> Self:
        """
        Translate a desired state status page into a status page object.
        """
        return cls(
            name=page.name,
            components=[
                StatusComponent.init_from_page_component(component=c)
                for c in page.components or []
            ],
        )


class StatusMaintenance(BaseModel):
    """
    Represents the desired state of a status maintenance.
    """

    name: str
    message: str
    schedule_start: str
    schedule_end: str

    @classmethod
    def init_from_maintenance(cls, maintenance: MaintenanceV1) -> Self:
        return cls(
            name=maintenance.name,
            message=maintenance.message.rstrip("\n"),
            schedule_start=maintenance.scheduled_start,
            schedule_end=maintenance.scheduled_end,
        )
