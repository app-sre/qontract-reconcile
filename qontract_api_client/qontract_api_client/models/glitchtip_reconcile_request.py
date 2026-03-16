from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.gi_instance import GIInstance


T = TypeVar("T", bound="GlitchtipReconcileRequest")


@_attrs_define
class GlitchtipReconcileRequest:
    """Request model for Glitchtip reconciliation.

    Attributes:
        instances (list[GIInstance]): List of Glitchtip instances to reconcile
        dry_run (bool | Unset): If True, only calculate actions without executing. Default: True (safety first!)
            Default: True.
    """

    instances: list[GIInstance]
    dry_run: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instances = []
        for instances_item_data in self.instances:
            instances_item = instances_item_data.to_dict()
            instances.append(instances_item)

        dry_run = self.dry_run

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "instances": instances,
        })
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.gi_instance import GIInstance

        d = dict(src_dict)
        instances = []
        _instances = d.pop("instances")
        for instances_item_data in _instances:
            instances_item = GIInstance.from_dict(instances_item_data)

            instances.append(instances_item)

        dry_run = d.pop("dry_run", UNSET)

        glitchtip_reconcile_request = cls(
            instances=instances,
            dry_run=dry_run,
        )

        glitchtip_reconcile_request.additional_properties = d
        return glitchtip_reconcile_request

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
