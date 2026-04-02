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

T = TypeVar("T", bound="AccountCreateCompleteAction")


@_attrs_define
class AccountCreateCompleteAction:
    """Account creation completed — contains the created account's name and UID.

    Attributes:
        account_name (str): Name of the created account
        account_uid (str): AWS account ID of the created account
        payer_account_name (str): Name of the payer account that managed creation
        action_type (Literal['create_complete'] | Unset):  Default: 'create_complete'.
    """

    account_name: str
    account_uid: str
    payer_account_name: str
    action_type: Literal["create_complete"] | Unset = "create_complete"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        account_uid = self.account_uid

        payer_account_name = self.payer_account_name

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
            "account_uid": account_uid,
            "payer_account_name": payer_account_name,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        account_name = d.pop("account_name")

        account_uid = d.pop("account_uid")

        payer_account_name = d.pop("payer_account_name")

        action_type = cast(
            Literal["create_complete"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "create_complete" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'create_complete', got '{action_type}'"
            )

        account_create_complete_action = cls(
            account_name=account_name,
            account_uid=account_uid,
            payer_account_name=payer_account_name,
            action_type=action_type,
        )

        account_create_complete_action.additional_properties = d
        return account_create_complete_action

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
