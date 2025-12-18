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

T = TypeVar("T", bound="UserSourcePagerDuty")


@_attrs_define
class UserSourcePagerDuty:
    """
    Attributes:
        instance_name (str):
        schedule_id (None | str):
        escalation_policy_id (None | str):
        provider (Literal['pagerduty'] | Unset):  Default: 'pagerduty'.
    """

    instance_name: str
    schedule_id: None | str
    escalation_policy_id: None | str
    provider: Literal["pagerduty"] | Unset = "pagerduty"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        instance_name = self.instance_name

        schedule_id: None | str
        schedule_id = self.schedule_id

        escalation_policy_id: None | str
        escalation_policy_id = self.escalation_policy_id

        provider = self.provider

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "instance_name": instance_name,
            "schedule_id": schedule_id,
            "escalation_policy_id": escalation_policy_id,
        })
        if provider is not UNSET:
            field_dict["provider"] = provider

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        instance_name = d.pop("instance_name")

        def _parse_schedule_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        schedule_id = _parse_schedule_id(d.pop("schedule_id"))

        def _parse_escalation_policy_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        escalation_policy_id = _parse_escalation_policy_id(
            d.pop("escalation_policy_id")
        )

        provider = cast(Literal["pagerduty"] | Unset, d.pop("provider", UNSET))
        if provider != "pagerduty" and not isinstance(provider, Unset):
            raise ValueError(f"provider must match const 'pagerduty', got '{provider}'")

        user_source_pager_duty = cls(
            instance_name=instance_name,
            schedule_id=schedule_id,
            escalation_policy_id=escalation_policy_id,
            provider=provider,
        )

        user_source_pager_duty.additional_properties = d
        return user_source_pager_duty

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
