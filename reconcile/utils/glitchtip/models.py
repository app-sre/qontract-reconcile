from typing import Optional
from pydantic import BaseModel, Field


class User(BaseModel):
    pk: int = Field(..., alias="id")
    email: str
    role: str
    pending: bool


class Team(BaseModel):
    pk: int = Field(..., alias="id")
    slug: str
    users: list[User] = []


class Project(BaseModel):
    pk: int = Field(..., alias="id")
    name: str
    slug: str
    platform: Optional[str]
    teams: list[Team] = []


class Organization(BaseModel):
    pk: int = Field(..., alias="id")
    name: str
    slug: str = ""
    projects: list[Project] = []
    teams: list[Team] = []
    users: list[User] = []
