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

T = TypeVar("T", bound="GlitchtipAlertActionUpdate")


@_attrs_define
class GlitchtipAlertActionUpdate:
    """Action: Update an existing project alert.

    Attributes:
        alert_name (str): Alert name
        instance (str): Glitchtip instance name
        organization (str): Organization name
        project (str): Project slug
        action_type (Literal['update'] | Unset):  Default: 'update'.
    """

    alert_name: str
    instance: str
    organization: str
    project: str
    action_type: Literal["update"] | Unset = "update"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        alert_name = self.alert_name

        instance = self.instance

        organization = self.organization

        project = self.project

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "alert_name": alert_name,
            "instance": instance,
            "organization": organization,
            "project": project,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        alert_name = d.pop("alert_name")

        instance = d.pop("instance")

        organization = d.pop("organization")

        project = d.pop("project")

        action_type = cast(Literal["update"] | Unset, d.pop("action_type", UNSET))
        if action_type != "update" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'update', got '{action_type}'"
            )

        glitchtip_alert_action_update = cls(
            alert_name=alert_name,
            instance=instance,
            organization=organization,
            project=project,
            action_type=action_type,
        )

        glitchtip_alert_action_update.additional_properties = d
        return glitchtip_alert_action_update

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
