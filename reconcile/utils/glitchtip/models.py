from typing import Optional
from pydantic import BaseModel, Field


class User(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    email: str
    role: str
    pending: bool = False


class Team(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    slug: str
    users: list[User] = []


class Project(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    platform: Optional[str]
    teams: list[Team] = []


class Organization(BaseModel):
    pk: Optional[int] = Field(None, alias="id")
    name: str
    slug: str = ""
    projects: list[Project] = []
    teams: list[Team] = []
    users: list[User] = []
