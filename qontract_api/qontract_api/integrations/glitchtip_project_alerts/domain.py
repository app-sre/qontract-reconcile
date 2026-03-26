"""Pydantic domain models for Glitchtip project alerts."""

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator
from qontract_utils.glitchtip_api import slugify

from qontract_api.models import Secret


class RecipientType(StrEnum):
    """Type of alert recipient."""

    EMAIL = "email"
    WEBHOOK = "webhook"


class GlitchtipProjectAlertRecipient(BaseModel, frozen=True):
    """Desired state for a single project alert recipient."""

    recipient_type: RecipientType = Field(
        ..., description="Recipient type: 'email' or 'webhook'"
    )
    url: str = Field(default="", description="Webhook URL (empty for email recipients)")

    @model_validator(mode="after")
    def validate_url(self) -> Self:
        if self.recipient_type == RecipientType.WEBHOOK and not self.url:
            raise ValueError("url must be set for webhook recipients")
        if self.recipient_type == RecipientType.EMAIL and self.url:
            raise ValueError("url must be empty for email recipients")
        return self


class GlitchtipProjectAlert(BaseModel, frozen=True):
    """Desired state for a single project alert."""

    name: str = Field(
        ..., description="Alert name (unique identifier within a project)"
    )
    timespan_minutes: int = Field(
        ..., description="Time window in minutes for alert evaluation"
    )
    quantity: int = Field(..., description="Number of events to trigger the alert")
    recipients: list[GlitchtipProjectAlertRecipient] = Field(
        default=[], description="List of alert recipients"
    )


class GlitchtipProject(BaseModel, frozen=True):
    """Desired state for a single Glitchtip project's alerts."""

    name: str = Field(..., description="Project name")
    slug: str = Field(
        default="",
        description="Project slug (URL-friendly identifier). Defaults to slugified name if not provided.",
    )
    alerts: list[GlitchtipProjectAlert] = Field(
        default=[], description="Desired alerts for this project"
    )

    @model_validator(mode="before")
    @classmethod
    def set_slug_from_name(cls, values: Any) -> Any:
        if isinstance(values, dict) and not values.get("slug"):
            values["slug"] = slugify(values["name"])
        return values


class GlitchtipOrganization(BaseModel, frozen=True):
    """Desired state for a single Glitchtip organization's projects."""

    name: str = Field(..., description="Organization name")
    projects: list[GlitchtipProject] = Field(
        default=[], description="Projects within this organization"
    )


class GlitchtipInstance(BaseModel, frozen=True):
    """Glitchtip instance configuration."""

    name: str = Field(..., description="Instance name (unique identifier)")
    console_url: str = Field(..., description="Glitchtip instance base URL")
    token: Secret = Field(..., description="Secret reference for the API token")
    read_timeout: int = Field(default=30, description="HTTP read timeout in seconds")
    max_retries: int = Field(default=3, description="Max HTTP retries")
    organizations: list[GlitchtipOrganization] = Field(
        default=[], description="Desired organizations with project alerts"
    )
