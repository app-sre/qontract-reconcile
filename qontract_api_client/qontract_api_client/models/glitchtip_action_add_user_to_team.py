from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="GlitchtipActionAddUserToTeam")


@_attrs_define
class GlitchtipActionAddUserToTeam:
    """Action: Add a user to a team.

    Attributes:
        email (str): User email
        instance (str): Glitchtip instance name
        organization (str): Organization name
        team_slug (str): Team slug
        action_type (Literal['add_user_to_team'] | Unset):  Default: 'add_user_to_team'.
        pk (int | None | Unset): User primary key (None when user is being invited in the same run)
    """

    email: str
    instance: str
    organization: str
    team_slug: str
    action_type: Literal["add_user_to_team"] | Unset = "add_user_to_team"
    pk: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        email = self.email

        instance = self.instance

        organization = self.organization

        team_slug = self.team_slug

        action_type = self.action_type

        pk: int | None | Unset
        if isinstance(self.pk, Unset):
            pk = UNSET
        else:
            pk = self.pk

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "email": email,
            "instance": instance,
            "organization": organization,
            "team_slug": team_slug,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type
        if pk is not UNSET:
            field_dict["pk"] = pk

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        email = d.pop("email")

        instance = d.pop("instance")

        organization = d.pop("organization")

        team_slug = d.pop("team_slug")

        action_type = cast(
            Literal["add_user_to_team"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "add_user_to_team" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'add_user_to_team', got '{action_type}'"
            )

        def _parse_pk(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        pk = _parse_pk(d.pop("pk", UNSET))

        glitchtip_action_add_user_to_team = cls(
            email=email,
            instance=instance,
            organization=organization,
            team_slug=team_slug,
            action_type=action_type,
            pk=pk,
        )

        glitchtip_action_add_user_to_team.additional_properties = d
        return glitchtip_action_add_user_to_team

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
