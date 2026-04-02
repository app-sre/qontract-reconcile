from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="AWSQuota")


@_attrs_define
class AWSQuota:
    """Service quota configuration for an AWS account.

    Attributes:
        quota_code (str): Quota code within the service (e.g., 'L-F678F1CE')
        service_code (str): AWS service code (e.g., 'vpc')
        value (float): Desired quota value
    """

    quota_code: str
    service_code: str
    value: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        quota_code = self.quota_code

        service_code = self.service_code

        value = self.value

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "quota_code": quota_code,
            "service_code": service_code,
            "value": value,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        quota_code = d.pop("quota_code")

        service_code = d.pop("service_code")

        value = d.pop("value")

        aws_quota = cls(
            quota_code=quota_code,
            service_code=service_code,
            value=value,
        )

        aws_quota.additional_properties = d
        return aws_quota

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
