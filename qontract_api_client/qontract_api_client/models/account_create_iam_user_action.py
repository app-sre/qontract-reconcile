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

T = TypeVar("T", bound="AccountCreateIAMUserAction")


@_attrs_define
class AccountCreateIAMUserAction:
    """IAM user creation action — contains account and user details.

    Attributes:
        account_name (str): Name of the account
        user_name (str): IAM user name created
        action_type (Literal['create_iam_user'] | Unset):  Default: 'create_iam_user'.
        detail (str | Unset): Additional detail Default: ''.
    """

    account_name: str
    user_name: str
    action_type: Literal["create_iam_user"] | Unset = "create_iam_user"
    detail: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        user_name = self.user_name

        action_type = self.action_type

        detail = self.detail

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
            "user_name": user_name,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type
        if detail is not UNSET:
            field_dict["detail"] = detail

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        account_name = d.pop("account_name")

        user_name = d.pop("user_name")

        action_type = cast(
            Literal["create_iam_user"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "create_iam_user" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'create_iam_user', got '{action_type}'"
            )

        detail = d.pop("detail", UNSET)

        account_create_iam_user_action = cls(
            account_name=account_name,
            user_name=user_name,
            action_type=action_type,
            detail=detail,
        )

        account_create_iam_user_action.additional_properties = d
        return account_create_iam_user_action

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
