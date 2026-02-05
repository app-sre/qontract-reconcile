from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.health_response_components import HealthResponseComponents


T = TypeVar("T", bound="HealthResponse")


@_attrs_define
class HealthResponse:
    """Overall health check response.

    Attributes:
        service (str): Service name
        status (str): Overall status: healthy, unhealthy, degraded
        version (str): Service version
        components (HealthResponseComponents | Unset): Component health statuses
    """

    service: str
    status: str
    version: str
    components: HealthResponseComponents | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        service = self.service

        status = self.status

        version = self.version

        components: dict[str, Any] | Unset = UNSET
        if not isinstance(self.components, Unset):
            components = self.components.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "service": service,
            "status": status,
            "version": version,
        })
        if components is not UNSET:
            field_dict["components"] = components

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.health_response_components import HealthResponseComponents

        d = dict(src_dict)
        service = d.pop("service")

        status = d.pop("status")

        version = d.pop("version")

        _components = d.pop("components", UNSET)
        components: HealthResponseComponents | Unset
        if isinstance(_components, Unset):
            components = UNSET
        else:
            components = HealthResponseComponents.from_dict(_components)

        health_response = cls(
            service=service,
            status=status,
            version=version,
            components=components,
        )

        health_response.additional_properties = d
        return health_response

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
