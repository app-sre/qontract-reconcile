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

T = TypeVar("T", bound="GlitchtipActionDeleteProject")


@_attrs_define
class GlitchtipActionDeleteProject:
    """Action: Delete a project.

    Attributes:
        instance (str): Glitchtip instance name
        organization (str): Organization name
        project_slug (str): Project slug
        action_type (Literal['delete_project'] | Unset):  Default: 'delete_project'.
    """

    instance: str
    organization: str
    project_slug: str
    action_type: Literal["delete_project"] | Unset = "delete_project"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instance = self.instance

        organization = self.organization

        project_slug = self.project_slug

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "instance": instance,
            "organization": organization,
            "project_slug": project_slug,
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

        action_type = cast(
            Literal["delete_project"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "delete_project" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'delete_project', got '{action_type}'"
            )

        glitchtip_action_delete_project = cls(
            instance=instance,
            organization=organization,
            project_slug=project_slug,
            action_type=action_type,
        )

        glitchtip_action_delete_project.additional_properties = d
        return glitchtip_action_delete_project

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
