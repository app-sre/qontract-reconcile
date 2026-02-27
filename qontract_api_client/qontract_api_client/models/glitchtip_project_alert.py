from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.glitchtip_project_alert_recipient import (
        GlitchtipProjectAlertRecipient,
    )


T = TypeVar("T", bound="GlitchtipProjectAlert")


@_attrs_define
class GlitchtipProjectAlert:
    """Desired state for a single project alert.

    Attributes:
        name (str): Alert name (unique identifier within a project)
        quantity (int): Number of events to trigger the alert
        timespan_minutes (int): Time window in minutes for alert evaluation
        recipients (list[GlitchtipProjectAlertRecipient] | Unset): List of alert recipients
    """

    name: str
    quantity: int
    timespan_minutes: int
    recipients: list[GlitchtipProjectAlertRecipient] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        quantity = self.quantity

        timespan_minutes = self.timespan_minutes

        recipients: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.recipients, Unset):
            recipients = []
            for recipients_item_data in self.recipients:
                recipients_item = recipients_item_data.to_dict()
                recipients.append(recipients_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
            "quantity": quantity,
            "timespan_minutes": timespan_minutes,
        })
        if recipients is not UNSET:
            field_dict["recipients"] = recipients

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.glitchtip_project_alert_recipient import (
            GlitchtipProjectAlertRecipient,
        )

        d = dict(src_dict)
        name = d.pop("name")

        quantity = d.pop("quantity")

        timespan_minutes = d.pop("timespan_minutes")

        _recipients = d.pop("recipients", UNSET)
        recipients: list[GlitchtipProjectAlertRecipient] | Unset = UNSET
        if _recipients is not UNSET:
            recipients = []
            for recipients_item_data in _recipients:
                recipients_item = GlitchtipProjectAlertRecipient.from_dict(
                    recipients_item_data
                )

                recipients.append(recipients_item)

        glitchtip_project_alert = cls(
            name=name,
            quantity=quantity,
            timespan_minutes=timespan_minutes,
            recipients=recipients,
        )

        glitchtip_project_alert.additional_properties = d
        return glitchtip_project_alert

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
