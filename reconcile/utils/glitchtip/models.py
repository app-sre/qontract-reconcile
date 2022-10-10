from typing import Optional
from pydantic import BaseModel, Field


class User(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    email: str
    role: str
    pending: bool = False

    def __lt__(self, other):
        return self.email < other.email


class Team(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    slug: str
    users: list[User] = []

    def __lt__(self, other):
        return self.slug < other.slug


class Project(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    platform: Optional[str]
    teams: list[Team] = []

    def __lt__(self, other):
        return self.name < other.name


class Organization(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    projects: list[Project] = []
    teams: list[Team] = []
    users: list[User] = []

    def __lt__(self, other):
        return self.name < other.name
