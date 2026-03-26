"""Pydantic models for the Internal Groups API."""

from pydantic import BaseModel, Field


class GroupMember(BaseModel, frozen=True):
    """A member of an LDAP group.

    Attributes:
        id: LDAP username (uid) of the member — never an email address
    """

    id: str = Field(..., description="LDAP username (uid) of the member")


class Group(BaseModel, frozen=True):
    """An LDAP group with its members.

    Attributes:
        name: Group name
        members: List of group members
    """

    name: str = Field(..., description="Group name")
    members: list[GroupMember] = Field(
        default_factory=list, description="Group members"
    )
