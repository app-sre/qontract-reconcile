from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="GlitchtipProjectAlertRecipient")


@_attrs_define
class GlitchtipProjectAlertRecipient:
    """Desired state for a single project alert recipient.

    Attributes:
        recipient_type (str): Recipient type: 'email' or 'webhook'
        url (str | Unset): Webhook URL (empty for email recipients) Default: ''.
    """

    recipient_type: str
    url: str | Unset = ""
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        recipient_type = self.recipient_type

        url = self.url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "recipient_type": recipient_type,
        })
        if url is not UNSET:
            field_dict["url"] = url

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        recipient_type = d.pop("recipient_type")

        url = d.pop("url", UNSET)

        glitchtip_project_alert_recipient = cls(
            recipient_type=recipient_type,
            url=url,
        )

        glitchtip_project_alert_recipient.additional_properties = d
        return glitchtip_project_alert_recipient

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
