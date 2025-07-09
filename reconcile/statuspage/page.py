from datetime import datetime
from typing import Self, cast

from pydantic import BaseModel

from reconcile.gql_definitions.maintenance.maintenances import (
    MaintenanceStatuspageAnnouncementV1,
)
from reconcile.gql_definitions.statuspage.statuspages import (
    MaintenanceV1,
    StatusPageComponentV1,
    StatusPageV1,
)
from reconcile.statuspage.status import (
    StatusProvider,
    build_status_provider_config,
)

PROVIDER_NAME = "statuspage"


class StatusComponent(BaseModel):
    """
    Represents a status page component from the desired state.
    """

    name: str
    display_name: str
    description: str | None
    group_name: str | None
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

    def desired_component_status(self) -> str | None:
        if self.status_management_enabled():
            for provider in self.status_provider_configs:
                status = provider.get_status()
                if status:
                    return status
            return "operational"
        return None

    class Config:
        arbitrary_types_allowed = True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StatusComponent):
            raise NotImplementedError("Cannot compare to non StatusComponent objects.")
        return (
            self.name == other.name
            and self.display_name == other.display_name
            and self.description == other.description
            and self.group_name == other.group_name
        )

    @classmethod
    def init_from_page_component(
        cls, component: StatusPageComponentV1, name_override: str | None = None
    ) -> Self:
        status_configs = [
            build_status_provider_config(cfg) for cfg in component.status_config or []
        ]
        return cls(
            name=name_override or component.name,
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


class StatusMaintenanceAnnouncement(BaseModel):
    """
    Represents the desired state of a status maintenance.
    """

    remind_subscribers: bool | None = None
    notify_subscribers_on_start: bool | None = None
    notify_subscribers_on_completion: bool | None = None

    @classmethod
    def init_from_announcement(
        cls, announcement: MaintenanceStatuspageAnnouncementV1
    ) -> Self:
        return cls(
            remind_subscribers=announcement.remind_subscribers,
            notify_subscribers_on_start=announcement.notify_subscribers_on_start,
            notify_subscribers_on_completion=announcement.notify_subscribers_on_completion,
        )


class StatusMaintenance(BaseModel):
    """
    Represents the desired state of a status maintenance.
    """

    name: str
    message: str
    schedule_start: datetime
    schedule_end: datetime
    components: list[StatusComponent]
    announcements: StatusMaintenanceAnnouncement

    @classmethod
    def init_from_maintenance(
        cls,
        maintenance: MaintenanceV1,
        page_components: list[StatusPageComponentV1],
    ) -> Self:
        affected_services = [a.name for a in maintenance.affected_services]
        affected_components = [
            StatusComponent.init_from_page_component(c, name_override=c.display_name)
            for c in page_components
            if c.app.name in affected_services
        ]
        if not affected_components:
            raise ValueError(
                f"No StatusPage component found for maintenance '{maintenance.name}'"
                f"via apps {affected_services}. Please define at least one StatusPage component."
            )

        statuspage_announcements = [
            StatusMaintenanceAnnouncement.init_from_announcement(
                cast(MaintenanceStatuspageAnnouncementV1, m)
            )
            for m in maintenance.announcements or []
            if m.provider == PROVIDER_NAME
        ]
        if len(statuspage_announcements) != 1:
            raise ValueError(
                f"Maintenance announcements must include exactly one item of provider {PROVIDER_NAME}"
            )

        return cls(
            name=maintenance.name,
            message=maintenance.message.rstrip("\n"),
            schedule_start=maintenance.scheduled_start,
            schedule_end=maintenance.scheduled_end,
            components=affected_components,
            announcements=statuspage_announcements[0],
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StatusMaintenance):
            raise NotImplementedError(
                "Cannot compare to non StatusMaintenance objects."
            )
        return (
            self.name == other.name
            and self.message == other.message
            and self.schedule_start == other.schedule_start
            and self.schedule_end == other.schedule_end
            and self.components == other.components
            and self.announcements == other.announcements
        )
