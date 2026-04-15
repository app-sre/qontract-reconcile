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

T = TypeVar("T", bound="GlitchtipActionUpdateProject")


@_attrs_define
class GlitchtipActionUpdateProject:
    """Action: Update a project's settings.

    Attributes:
        instance (str): Glitchtip instance name
        name (str): Project name
        organization (str): Organization name
        project_slug (str): Project slug
        action_type (Literal['update_project'] | Unset):  Default: 'update_project'.
        event_throttle_rate (int | Unset): Event throttle rate (0 = unlimited) Default: 0.
        platform (None | str | Unset): Project platform
    """

    instance: str
    name: str
    organization: str
    project_slug: str
    action_type: Literal["update_project"] | Unset = "update_project"
    event_throttle_rate: int | Unset = 0
    platform: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instance = self.instance

        name = self.name

        organization = self.organization

        project_slug = self.project_slug

        action_type = self.action_type

        event_throttle_rate = self.event_throttle_rate

        platform: None | str | Unset
        if isinstance(self.platform, Unset):
            platform = UNSET
        else:
            platform = self.platform

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "instance": instance,
            "name": name,
            "organization": organization,
            "project_slug": project_slug,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type
        if event_throttle_rate is not UNSET:
            field_dict["event_throttle_rate"] = event_throttle_rate
        if platform is not UNSET:
            field_dict["platform"] = platform

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        instance = d.pop("instance")

        name = d.pop("name")

        organization = d.pop("organization")

        project_slug = d.pop("project_slug")

        action_type = cast(
            Literal["update_project"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "update_project" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'update_project', got '{action_type}'"
            )

        event_throttle_rate = d.pop("event_throttle_rate", UNSET)

        def _parse_platform(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        platform = _parse_platform(d.pop("platform", UNSET))

        glitchtip_action_update_project = cls(
            instance=instance,
            name=name,
            organization=organization,
            project_slug=project_slug,
            action_type=action_type,
            event_throttle_rate=event_throttle_rate,
            platform=platform,
        )

        glitchtip_action_update_project.additional_properties = d
        return glitchtip_action_update_project

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
