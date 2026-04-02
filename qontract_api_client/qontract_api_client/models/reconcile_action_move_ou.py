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

T = TypeVar("T", bound="ReconcileActionMoveOU")


@_attrs_define
class ReconcileActionMoveOU:
    """Action: account moved to a different OU.

    Attributes:
        account_name (str): Account name
        ou (str): Target OU path
        action_type (Literal['move_ou'] | Unset):  Default: 'move_ou'.
    """

    account_name: str
    ou: str
    action_type: Literal["move_ou"] | Unset = "move_ou"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        ou = self.ou

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
            "ou": ou,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        account_name = d.pop("account_name")

        ou = d.pop("ou")

        action_type = cast(Literal["move_ou"] | Unset, d.pop("action_type", UNSET))
        if action_type != "move_ou" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'move_ou', got '{action_type}'"
            )

        reconcile_action_move_ou = cls(
            account_name=account_name,
            ou=ou,
            action_type=action_type,
        )

        reconcile_action_move_ou.additional_properties = d
        return reconcile_action_move_ou

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
