from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="AWSAccountRequest")


@_attrs_define
class AWSAccountRequest:
    """Request to create a new AWS account under a payer account.

    Attributes:
        email (str): Account owner email
        name (str): Account name
        path (str): App-interface path to account request file
        uid (None | str | Unset): Existing account ID for takeover scenarios
    """

    email: str
    name: str
    path: str
    uid: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        email = self.email

        name = self.name

        path = self.path

        uid: None | str | Unset
        if isinstance(self.uid, Unset):
            uid = UNSET
        else:
            uid = self.uid

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "email": email,
            "name": name,
            "path": path,
        })
        if uid is not UNSET:
            field_dict["uid"] = uid

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        email = d.pop("email")

        name = d.pop("name")

        path = d.pop("path")

        def _parse_uid(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        uid = _parse_uid(d.pop("uid", UNSET))

        aws_account_request = cls(
            email=email,
            name=name,
            path=path,
            uid=uid,
        )

        aws_account_request.additional_properties = d
        return aws_account_request

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
