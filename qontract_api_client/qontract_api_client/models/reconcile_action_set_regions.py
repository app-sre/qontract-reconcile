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

T = TypeVar("T", bound="ReconcileActionSetRegions")


@_attrs_define
class ReconcileActionSetRegions:
    """Action: supported regions updated.

    Attributes:
        account_name (str): Account name
        action_type (Literal['set_regions'] | Unset):  Default: 'set_regions'.
        disabled (list[str] | Unset): Regions disabled
        enabled (list[str] | Unset): Regions enabled
    """

    account_name: str
    action_type: Literal["set_regions"] | Unset = "set_regions"
    disabled: list[str] | Unset = UNSET
    enabled: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        action_type = self.action_type

        disabled: list[str] | Unset = UNSET
        if not isinstance(self.disabled, Unset):
            disabled = self.disabled

        enabled: list[str] | Unset = UNSET
        if not isinstance(self.enabled, Unset):
            enabled = self.enabled

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type
        if disabled is not UNSET:
            field_dict["disabled"] = disabled
        if enabled is not UNSET:
            field_dict["enabled"] = enabled

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        account_name = d.pop("account_name")

        action_type = cast(Literal["set_regions"] | Unset, d.pop("action_type", UNSET))
        if action_type != "set_regions" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'set_regions', got '{action_type}'"
            )

        disabled = cast(list[str], d.pop("disabled", UNSET))

        enabled = cast(list[str], d.pop("enabled", UNSET))

        reconcile_action_set_regions = cls(
            account_name=account_name,
            action_type=action_type,
            disabled=disabled,
            enabled=enabled,
        )

        reconcile_action_set_regions.additional_properties = d
        return reconcile_action_set_regions

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
