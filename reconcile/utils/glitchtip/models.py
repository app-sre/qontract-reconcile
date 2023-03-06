from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
    root_validator,
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


class Project(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    platform: Optional[str]
    teams: list[Team] = []

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
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)


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
