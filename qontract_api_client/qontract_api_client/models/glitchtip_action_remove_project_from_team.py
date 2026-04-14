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

T = TypeVar("T", bound="GlitchtipActionRemoveProjectFromTeam")


@_attrs_define
class GlitchtipActionRemoveProjectFromTeam:
    """Action: Remove a project from a team.

    Attributes:
        instance (str): Glitchtip instance name
        organization (str): Organization name
        project_slug (str): Project slug
        team_slug (str): Team slug
        action_type (Literal['remove_project_from_team'] | Unset):  Default: 'remove_project_from_team'.
    """

    instance: str
    organization: str
    project_slug: str
    team_slug: str
    action_type: Literal["remove_project_from_team"] | Unset = (
        "remove_project_from_team"
    )
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instance = self.instance

        organization = self.organization

        project_slug = self.project_slug

        team_slug = self.team_slug

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "instance": instance,
            "organization": organization,
            "project_slug": project_slug,
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

        project_slug = d.pop("project_slug")

        team_slug = d.pop("team_slug")

        action_type = cast(
            Literal["remove_project_from_team"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "remove_project_from_team" and not isinstance(
            action_type, Unset
        ):
            raise ValueError(
                f"action_type must match const 'remove_project_from_team', got '{action_type}'"
            )

        glitchtip_action_remove_project_from_team = cls(
            instance=instance,
            organization=organization,
            project_slug=project_slug,
            team_slug=team_slug,
            action_type=action_type,
        )

        glitchtip_action_remove_project_from_team.additional_properties = d
        return glitchtip_action_remove_project_from_team

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
