from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="ChatResponse")


@_attrs_define
class ChatResponse:
    """Response model for a posted Slack message.

    Immutable model returning the Slack API response fields.

    Attributes:
        ts: Message timestamp
        channel: Channel ID where the message was posted
        thread_ts: Thread timestamp if this was a threaded reply

        Attributes:
            channel (str): Channel ID where the message was posted
            ts (str): Message timestamp
            thread_ts (None | str | Unset): Thread timestamp if this was a threaded reply
    """

    channel: str
    ts: str
    thread_ts: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        channel = self.channel

        ts = self.ts

        thread_ts: None | str | Unset
        if isinstance(self.thread_ts, Unset):
            thread_ts = UNSET
        else:
            thread_ts = self.thread_ts

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "channel": channel,
            "ts": ts,
        })
        if thread_ts is not UNSET:
            field_dict["thread_ts"] = thread_ts

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        channel = d.pop("channel")

        ts = d.pop("ts")

        def _parse_thread_ts(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        thread_ts = _parse_thread_ts(d.pop("thread_ts", UNSET))

        chat_response = cls(
            channel=channel,
            ts=ts,
            thread_ts=thread_ts,
        )

        chat_response.additional_properties = d
        return chat_response

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
