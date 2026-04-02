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

T = TypeVar("T", bound="ReconcileActionRequestQuota")


@_attrs_define
class ReconcileActionRequestQuota:
    """Action: service quota increase requested.

    Attributes:
        account_name (str): Account name
        quota_code (str): AWS quota code
        service_code (str): AWS service code
        value (float): Requested quota value
        action_type (Literal['request_quota'] | Unset):  Default: 'request_quota'.
    """

    account_name: str
    quota_code: str
    service_code: str
    value: float
    action_type: Literal["request_quota"] | Unset = "request_quota"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        quota_code = self.quota_code

        service_code = self.service_code

        value = self.value

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
            "quota_code": quota_code,
            "service_code": service_code,
            "value": value,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        account_name = d.pop("account_name")

        quota_code = d.pop("quota_code")

        service_code = d.pop("service_code")

        value = d.pop("value")

        action_type = cast(
            Literal["request_quota"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "request_quota" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'request_quota', got '{action_type}'"
            )

        reconcile_action_request_quota = cls(
            account_name=account_name,
            quota_code=quota_code,
            service_code=service_code,
            value=value,
            action_type=action_type,
        )

        reconcile_action_request_quota.additional_properties = d
        return reconcile_action_request_quota

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
