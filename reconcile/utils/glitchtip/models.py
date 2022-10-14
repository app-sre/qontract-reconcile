import re
from typing import Optional
from pydantic import BaseModel, Field, root_validator


def slugify(value: str):
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

    def __lt__(self, other):
        return self.email < other.email

    def __eq__(self, other):
        return self.email == other.email

    def __hash__(self):
        return hash(self.email)


class Team(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str = ""
    slug: str = ""
    users: list[User] = []

    @root_validator(pre=True)
    def name_xor_slug_must_be_set(cls, values):  # pylint: disable=no-self-argument
        assert ("name" in values or "slug" in values) and not (
            "name" in values and "slug" in values
        ), "name xor slug must be set!"
        return values

    @root_validator
    def slugify(cls, values):  # pylint: disable=no-self-argument
        values["slug"] = values.get("slug") or slugify(values.get("name"))
        values["name"] = slugify(values.get("name")) or values.get("slug")
        return values

    def __lt__(self, other):
        return self.slug < other.slug

    def __eq__(self, other):
        return self.slug == other.slug

    def __hash__(self):
        return hash(self.slug)


class Project(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    platform: Optional[str]
    teams: list[Team] = []

    @root_validator
    def slugify(cls, values):  # pylint: disable=no-self-argument
        values["slug"] = values.get("slug") or slugify(values.get("name"))
        return values

    def __lt__(self, other):
        return self.name < other.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)


class Organization(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    projects: list[Project] = []
    teams: list[Team] = []
    users: list[User] = []

    @root_validator
    def slugify(cls, values):  # pylint: disable=no-self-argument
        values["slug"] = values.get("slug") or slugify(values.get("name"))
        return values

    def __lt__(self, other):
        return self.name < other.name

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)
