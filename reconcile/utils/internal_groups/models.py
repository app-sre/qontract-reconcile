from __future__ import annotations

from enum import StrEnum

from pydantic import (
    BaseModel,
    Field,
)


class EntityType(StrEnum):
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


class Group(BaseModel, validate_by_name=True, validate_by_alias=True):
    name: str
    description: str
    member_approval_type: str = Field("self-service", alias="memberApprovalType")
    contact_list: str = Field(..., alias="contactList")
    owners: list[Entity]
    display_name: str = Field(..., alias="displayName")
    notes: str | None = None
    rover_group_member_query: str | None = Field(
        None, alias="roverGroupMemberQuery", exclude=True
    )
    rover_group_inclusions: list[Entity] | None = Field(
        None, alias="roverGroupInclusions", exclude=True
    )
    rover_group_exclusions: list[Entity] | None = Field(
        None, alias="roverGroupExclusions", exclude=True
    )
    members: list[Entity] = []
    member_of: list[str] | None = Field(None, alias="memberOf", exclude=True)
    namespace: str | None = Field(None, exclude=True)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Group):
            raise NotImplementedError("Cannot compare to non Group objects.")
        return (
            self.description == other.description
            and self.member_approval_type == other.member_approval_type
            and self.contact_list == other.contact_list
            and set(self.owners) == set(other.owners)
            and self.display_name == other.display_name
            and self.notes == other.notes
            and set(self.members) == set(other.members)
        )
