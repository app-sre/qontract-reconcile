"""Pydantic models for Glitchtip API.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel
- Immutable with frozen=True (thread-safe)
- Type-safe throughout
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RecipientType(StrEnum):
    """Type of alert recipient."""

    EMAIL = "email"
    WEBHOOK = "webhook"


class ProjectAlertRecipient(BaseModel):
    """A recipient for a Glitchtip project alert.

    Attributes:
        pk: Primary key (id) of the recipient, set by Glitchtip API
        recipient_type: Type of recipient (email or webhook)
        url: Webhook URL (only relevant for webhook recipients)
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    pk: int | None = Field(None, alias="id")
    recipient_type: RecipientType = Field(..., alias="recipientType")
    url: str = ""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectAlertRecipient):
            raise NotImplementedError(
                "Cannot compare to non ProjectAlertRecipient objects."
            )

        return self.recipient_type == other.recipient_type and self.url == other.url

    def __hash__(self) -> int:
        return hash((self.recipient_type, self.url))


class ProjectAlert(BaseModel):
    """A Glitchtip project alert configuration.

    Attributes:
        pk: Primary key (id) of the alert, set by Glitchtip API
        name: Alert name (unique identifier within a project)
        timespan_minutes: Time window in minutes for alert evaluation
        quantity: Number of events to trigger the alert
        recipients: List of alert recipients
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    pk: int | None = Field(None, alias="id")
    name: str
    timespan_minutes: int = Field(..., alias="timespanMinutes")
    quantity: int
    recipients: list[ProjectAlertRecipient] = Field([], alias="alertRecipients")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectAlert):
            raise NotImplementedError("Cannot compare to non ProjectAlert objects.")

        return (
            self.timespan_minutes == other.timespan_minutes
            and self.quantity == other.quantity
            and set(self.recipients) == set(other.recipients)
        )

    def __hash__(self) -> int:
        return hash((self.timespan_minutes, self.quantity, frozenset(self.recipients)))


class Project(BaseModel):
    """A Glitchtip project.

    Attributes:
        pk: Primary key (id) of the project, set by Glitchtip API
        name: Project name
        slug: Project slug (URL-friendly identifier)
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    pk: int | None = Field(None, alias="id")
    name: str
    slug: str = ""


class Organization(BaseModel):
    """A Glitchtip organization.

    Attributes:
        pk: Primary key (id) of the organization, set by Glitchtip API
        name: Organization name
        slug: Organization slug (URL-friendly identifier)
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    pk: int | None = Field(None, alias="id")
    name: str
    slug: str = ""
