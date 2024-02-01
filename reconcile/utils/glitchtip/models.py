from __future__ import annotations

import re
from collections.abc import MutableMapping
from enum import Enum
from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
    root_validator,
    validator,
)


def slugify(value: str) -> str:
    """Convert value into a slug.

    Adapted copy of https://docs.djangoproject.com/en/4.1/_modules/django/utils/text/#slugify
    """
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


class User(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    email: str
    role: str
    pending: bool = False

    def __lt__(self, other: User) -> bool:
        return self.email < other.email

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, User):
            raise NotImplementedError("Cannot compare to non User objects.")
        return self.email == other.email

    def __hash__(self) -> int:
        return hash(self.email)


class Team(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str = ""
    slug: str = ""
    users: list[User] = []

    @root_validator(pre=True)
    def name_xor_slug_must_be_set(  # pylint: disable=no-self-argument
        cls, values: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        assert ("name" in values or "slug" in values) and not (
            "name" in values and "slug" in values
        ), "name xor slug must be set!"
        return values

    @root_validator
    def slugify(  # pylint: disable=no-self-argument
        cls, values: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        values["slug"] = values.get("slug") or slugify(values.get("name", ""))
        values["name"] = slugify(values.get("name", "")) or values.get("slug")
        return values

    def __lt__(self, other: Team) -> bool:
        return self.slug < other.slug

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Team):
            raise NotImplementedError("Cannot compare to non Team objects.")
        return self.slug == other.slug

    def __hash__(self) -> int:
        return hash(self.slug)


class ProjectKey(BaseModel):
    dsn: str
    security_endpoint: str


class RecipientType(Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"


class ProjectAlertRecipient(BaseModel):
    pk: Optional[int]
    recipient_type: RecipientType = Field(..., alias="recipientType")
    url: str = ""

    class Config:
        allow_population_by_field_name = True
        use_enum_values = True

    @validator("recipient_type")
    def recipient_type_enforce_enum_type(  # pylint: disable=no-self-argument
        cls, v: str | RecipientType
    ) -> RecipientType:
        if isinstance(v, RecipientType):
            return v
        return RecipientType[v.upper()]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectAlertRecipient):
            raise NotImplementedError(
                "Cannot compare to non ProjectAlertRecipient objects."
            )

        return self.recipient_type == other.recipient_type and self.url == other.url

    def __hash__(self) -> int:
        return hash((self.recipient_type, self.url))


class ProjectAlert(BaseModel):
    pk: Optional[int]
    name: str
    timespan_minutes: int
    quantity: int
    recipients: list[ProjectAlertRecipient] = Field([], alias="alertRecipients")

    class Config:
        allow_population_by_field_name = True

    @root_validator
    def empty_name(  # pylint: disable=no-self-argument
        cls, values: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        # name is an empty string if the alert was created manually because it can't be set via UI
        # use the pk instead.
        values["name"] = values.get("name") or f'alert-{values.get("pk")}'
        return values

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectAlert):
            raise NotImplementedError("Cannot compare to non ProjectAlert objects.")

        return (
            self.timespan_minutes == other.timespan_minutes
            and self.quantity == other.quantity
            and set(self.recipients) == set(other.recipients)
        )


class Project(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    platform: Optional[str]
    teams: list[Team] = []
    alerts: list[ProjectAlert] = []
    event_throttle_rate: int = Field(0, alias="eventThrottleRate")

    class Config:
        allow_population_by_field_name = True

    @root_validator
    def slugify(  # pylint: disable=no-self-argument
        cls, values: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        values["slug"] = values.get("slug") or slugify(values["name"])
        return values

    def __lt__(self, other: Project) -> bool:
        return self.name < other.name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Project):
            raise NotImplementedError("Cannot compare to non Project objects.")
        # use the slug attribute to compare projects
        # it can't be changed by the Glitchtip users, so it's more reliable
        # and can be used to detect changes in the project name
        return self.slug == other.slug

    def diff(self, other: Project) -> bool:
        return (
            self.name != other.name
            or self.platform != other.platform
            or self.event_throttle_rate != other.event_throttle_rate
        )

    def __hash__(self) -> int:
        return hash(self.slug)


class Organization(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    projects: list[Project] = []
    teams: list[Team] = []
    users: list[User] = []

    @root_validator
    def slugify(  # pylint: disable=no-self-argument
        cls, values: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        values["slug"] = values.get("slug") or slugify(values["name"])
        return values

    def __lt__(self, other: Organization) -> bool:
        return self.name < other.name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Organization):
            raise NotImplementedError("Cannot compare to non Organization objects.")
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)
