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

T = TypeVar("T", bound="ReconcileActionSetSecurityContact")


@_attrs_define
class ReconcileActionSetSecurityContact:
    """Action: security contact set.

    Attributes:
        account_name (str): Account name
        action_type (Literal['set_security_contact'] | Unset):  Default: 'set_security_contact'.
    """

    account_name: str
    action_type: Literal["set_security_contact"] | Unset = "set_security_contact"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        account_name = d.pop("account_name")

        action_type = cast(
            Literal["set_security_contact"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "set_security_contact" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'set_security_contact', got '{action_type}'"
            )

        reconcile_action_set_security_contact = cls(
            account_name=account_name,
            action_type=action_type,
        )

        reconcile_action_set_security_contact.additional_properties = d
        return reconcile_action_set_security_contact

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
