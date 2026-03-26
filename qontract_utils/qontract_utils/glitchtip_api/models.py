"""Pydantic models for Glitchtip API.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel
- Immutable with frozen=True (thread-safe)
- Type-safe throughout
"""

import re
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


def slugify(value: str) -> str:
    """Convert value into a slug.

    Adapted from https://docs.djangoproject.com/en/4.1/_modules/django/utils/text/#slugify
    """
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


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
        platform: Project platform (e.g., "python", "javascript")
        event_throttle_rate: Event throttle rate (0 = no throttle)
        team_slugs: Team slugs this project belongs to (derived from API response)
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    pk: int | None = Field(None, alias="id")
    name: str
    slug: str = ""
    platform: str | None = None
    event_throttle_rate: int = Field(0, alias="eventThrottleRate")
    team_slugs: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def extract_team_slugs(cls, values: Any) -> Any:
        """Extract team slugs from nested team objects in the API response."""
        if (
            isinstance(values, dict)
            and "teams" in values
            and not values.get("team_slugs")
        ):
            raw_teams = values.get("teams", [])
            values = dict(values)
            values["team_slugs"] = [
                t.get("slug", "")
                for t in raw_teams
                if isinstance(t, dict) and t.get("slug")
            ]
        return values


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


class User(BaseModel):
    """A Glitchtip organization user (member).

    Attributes:
        pk: Primary key (id) of the member, set by Glitchtip API
        email: User email address (used as unique identifier)
        role: Organization role (e.g., "member", "admin", "owner")
        pending: Whether the user invitation is pending acceptance
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    pk: int | None = Field(None, alias="id")
    email: str
    role: str = Field("member", alias="orgRole")
    pending: bool = False

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, User):
            raise NotImplementedError("Cannot compare to non User objects.")
        return self.email == other.email

    def __hash__(self) -> int:
        return hash(self.email)


class Team(BaseModel):
    """A Glitchtip team.

    Attributes:
        pk: Primary key (id) of the team, set by Glitchtip API
        slug: Team slug (URL-friendly identifier, used as unique key)
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    pk: int | None = Field(None, alias="id")
    slug: str = ""

    @model_validator(mode="before")
    @classmethod
    def derive_slug_from_name(cls, values: Any) -> Any:
        """Derive slug from name if slug is not provided (Django slugify)."""
        if isinstance(values, dict) and not values.get("slug") and values.get("name"):
            values = dict(values)
            values["slug"] = slugify(values["name"])
        return values

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Team):
            raise NotImplementedError("Cannot compare to non Team objects.")
        return self.slug == other.slug

    def __hash__(self) -> int:
        return hash(self.slug)

    @model_validator(mode="after")
    def validate_slug(self) -> Self:
        """Ensure slug is not empty."""
        if not self.slug:
            raise ValueError("Team slug cannot be empty")
        return self
