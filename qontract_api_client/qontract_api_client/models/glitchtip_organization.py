from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.glitchtip_project import GlitchtipProject


T = TypeVar("T", bound="GlitchtipOrganization")


@_attrs_define
class GlitchtipOrganization:
    """Desired state for a single Glitchtip organization's projects.

    Attributes:
        name (str): Organization name
        projects (list[GlitchtipProject] | Unset): Projects within this organization
    """

    name: str
    projects: list[GlitchtipProject] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        projects: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.projects, Unset):
            projects = []
            for projects_item_data in self.projects:
                projects_item = projects_item_data.to_dict()
                projects.append(projects_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
        })
        if projects is not UNSET:
            field_dict["projects"] = projects

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.glitchtip_project import GlitchtipProject

        d = dict(src_dict)
        name = d.pop("name")

        _projects = d.pop("projects", UNSET)
        projects: list[GlitchtipProject] | Unset = UNSET
        if _projects is not UNSET:
            projects = []
            for projects_item_data in _projects:
                projects_item = GlitchtipProject.from_dict(projects_item_data)

                projects.append(projects_item)

        glitchtip_organization = cls(
            name=name,
            projects=projects,
        )

        glitchtip_organization.additional_properties = d
        return glitchtip_organization

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
