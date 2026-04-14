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

T = TypeVar("T", bound="GlitchtipActionCreateTeam")


@_attrs_define
class GlitchtipActionCreateTeam:
    """Action: Create a team in an organization.

    Attributes:
        instance (str): Glitchtip instance name
        organization (str): Organization name
        team_slug (str): Team slug
        action_type (Literal['create_team'] | Unset):  Default: 'create_team'.
    """

    instance: str
    organization: str
    team_slug: str
    action_type: Literal["create_team"] | Unset = "create_team"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instance = self.instance

        organization = self.organization

        team_slug = self.team_slug

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "instance": instance,
            "organization": organization,
            "team_slug": team_slug,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        instance = d.pop("instance")

        organization = d.pop("organization")

        team_slug = d.pop("team_slug")

        action_type = cast(Literal["create_team"] | Unset, d.pop("action_type", UNSET))
        if action_type != "create_team" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'create_team', got '{action_type}'"
            )

        glitchtip_action_create_team = cls(
            instance=instance,
            organization=organization,
            team_slug=team_slug,
            action_type=action_type,
        )

        glitchtip_action_create_team.additional_properties = d
        return glitchtip_action_create_team

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
