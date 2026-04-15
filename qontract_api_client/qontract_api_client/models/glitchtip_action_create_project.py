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

T = TypeVar("T", bound="GlitchtipActionCreateProject")


@_attrs_define
class GlitchtipActionCreateProject:
    """Action: Create a project in an organization.

    Attributes:
        instance (str): Glitchtip instance name
        organization (str): Organization name
        project_name (str): Project name
        action_type (Literal['create_project'] | Unset):  Default: 'create_project'.
        event_throttle_rate (int | Unset): Event throttle rate (0 = unlimited) Default: 0.
        platform (None | str | Unset): Project platform
        teams (list[str] | Unset): Team slugs to associate with the project (first team used for creation)
    """

    instance: str
    organization: str
    project_name: str
    action_type: Literal["create_project"] | Unset = "create_project"
    event_throttle_rate: int | Unset = 0
    platform: None | str | Unset = UNSET
    teams: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instance = self.instance

        organization = self.organization

        project_name = self.project_name

        action_type = self.action_type

        event_throttle_rate = self.event_throttle_rate

        platform: None | str | Unset
        if isinstance(self.platform, Unset):
            platform = UNSET
        else:
            platform = self.platform

        teams: list[str] | Unset = UNSET
        if not isinstance(self.teams, Unset):
            teams = self.teams

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "instance": instance,
            "organization": organization,
            "project_name": project_name,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type
        if event_throttle_rate is not UNSET:
            field_dict["event_throttle_rate"] = event_throttle_rate
        if platform is not UNSET:
            field_dict["platform"] = platform
        if teams is not UNSET:
            field_dict["teams"] = teams

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        instance = d.pop("instance")

        organization = d.pop("organization")

        project_name = d.pop("project_name")

        action_type = cast(
            Literal["create_project"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "create_project" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'create_project', got '{action_type}'"
            )

        event_throttle_rate = d.pop("event_throttle_rate", UNSET)

        def _parse_platform(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        platform = _parse_platform(d.pop("platform", UNSET))

        teams = cast(list[str], d.pop("teams", UNSET))

        glitchtip_action_create_project = cls(
            instance=instance,
            organization=organization,
            project_name=project_name,
            action_type=action_type,
            event_throttle_rate=event_throttle_rate,
            platform=platform,
            teams=teams,
        )

        glitchtip_action_create_project.additional_properties = d
        return glitchtip_action_create_project

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
