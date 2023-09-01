from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    Field,
)


class EntityType(str, Enum):
    USER = "user"
    SERVICE_ACCOUNT = "serviceaccount"
    DELETED_USER = "deleteduser"


class Entity(BaseModel):
    type: EntityType
    id: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Entity):
            raise NotImplementedError("Cannot compare to non Entity objects.")
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class Group(BaseModel):
    name: str
    description: str
    member_approval_type: str = Field("self-service", alias="memberApprovalType")
    contact_list: str = Field(..., alias="contactList")
    owners: list[Entity]
    display_name: str = Field(..., alias="displayName")
    notes: Optional[str] = None
    rover_group_member_query: Optional[str] = Field(None, alias="roverGroupMemberQuery")
    rover_group_inclusions: Optional[list[Entity]] = Field(
        None, alias="roverGroupInclusions"
    )
    rover_group_exclusions: Optional[list[Entity]] = Field(
        None, alias="roverGroupExclusions"
    )
    members: list[Entity] = []
    member_of: Optional[list[str]] = Field(None, alias="memberOf")
    namespace: Optional[str] = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Group):
            raise NotImplementedError("Cannot compare to non Group objects.")
        return (
            self.description == other.description
            and self.member_approval_type == other.member_approval_type
            and self.contact_list == other.contact_list
            and self.owners == other.owners
            and self.display_name == other.display_name
            and self.notes == other.notes
            and set(self.members) == set(other.members)
        )

    class Config:
        allow_population_by_field_name = True
        # exclude read-only fields in the json/dict dumps
        fields = {
            "rover_group_member_query": {"exclude": True},
            "rover_group_inclusions": {"exclude": True},
            "rover_group_exclusions": {"exclude": True},
            "member_of": {"exclude": True},
            "namespace": {"exclude": True},
        }
