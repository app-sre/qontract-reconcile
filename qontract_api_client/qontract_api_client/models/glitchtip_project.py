from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.glitchtip_project_alert import GlitchtipProjectAlert


T = TypeVar("T", bound="GlitchtipProject")


@_attrs_define
class GlitchtipProject:
    """Desired state for a single Glitchtip project's alerts.

    Attributes:
        name (str): Project name
        alerts (list[GlitchtipProjectAlert] | Unset): Desired alerts for this project
        slug (str | Unset): Project slug (URL-friendly identifier). Defaults to slugified name if not provided. Default:
            ''.
    """

    name: str
    alerts: list[GlitchtipProjectAlert] | Unset = UNSET
    slug: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        alerts: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.alerts, Unset):
            alerts = []
            for alerts_item_data in self.alerts:
                alerts_item = alerts_item_data.to_dict()
                alerts.append(alerts_item)

        slug = self.slug

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
        })
        if alerts is not UNSET:
            field_dict["alerts"] = alerts
        if slug is not UNSET:
            field_dict["slug"] = slug

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.glitchtip_project_alert import GlitchtipProjectAlert

        d = dict(src_dict)
        name = d.pop("name")

        _alerts = d.pop("alerts", UNSET)
        alerts: list[GlitchtipProjectAlert] | Unset = UNSET
        if _alerts is not UNSET:
            alerts = []
            for alerts_item_data in _alerts:
                alerts_item = GlitchtipProjectAlert.from_dict(alerts_item_data)

                alerts.append(alerts_item)

        slug = d.pop("slug", UNSET)

        glitchtip_project = cls(
            name=name,
            alerts=alerts,
            slug=slug,
        )

        glitchtip_project.additional_properties = d
        return glitchtip_project

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
