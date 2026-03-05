from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.secret import Secret


T = TypeVar("T", bound="ChatRequest")


@_attrs_define
class ChatRequest:
    """Request model for posting a Slack message.

    Immutable model with all fields required to send a chat message.

    Attributes:
        workspace_name: Slack workspace name
        channel: Channel name to post to
        text: Message text
        thread_ts: Optional thread timestamp for replies
        icon_emoji: Emoji to use as the message icon
        icon_url: URL to an image to use as the message icon
        username: Bot username to display
        secret: Secret reference for Slack bot token

        Attributes:
            channel (str): Channel name to post to (e.g., 'sd-app-sre-reconcile')
            secret (Secret): Reference to a secret stored in a secret manager.
            text (str): Message text
            workspace_name (str): Slack workspace name
            icon_emoji (None | str | Unset): Emoji to use as the message icon (e.g., ':robot_face:')
            icon_url (None | str | Unset): URL to an image to use as the message icon
            thread_ts (None | str | Unset): Optional thread timestamp for replies
            username (None | str | Unset): Bot username to display
    """

    channel: str
    secret: Secret
    text: str
    workspace_name: str
    icon_emoji: None | str | Unset = UNSET
    icon_url: None | str | Unset = UNSET
    thread_ts: None | str | Unset = UNSET
    username: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        channel = self.channel

        secret = self.secret.to_dict()

        text = self.text

        workspace_name = self.workspace_name

        icon_emoji: None | str | Unset
        if isinstance(self.icon_emoji, Unset):
            icon_emoji = UNSET
        else:
            icon_emoji = self.icon_emoji

        icon_url: None | str | Unset
        if isinstance(self.icon_url, Unset):
            icon_url = UNSET
        else:
            icon_url = self.icon_url

        thread_ts: None | str | Unset
        if isinstance(self.thread_ts, Unset):
            thread_ts = UNSET
        else:
            thread_ts = self.thread_ts

        username: None | str | Unset
        if isinstance(self.username, Unset):
            username = UNSET
        else:
            username = self.username

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "channel": channel,
            "secret": secret,
            "text": text,
            "workspace_name": workspace_name,
        })
        if icon_emoji is not UNSET:
            field_dict["icon_emoji"] = icon_emoji
        if icon_url is not UNSET:
            field_dict["icon_url"] = icon_url
        if thread_ts is not UNSET:
            field_dict["thread_ts"] = thread_ts
        if username is not UNSET:
            field_dict["username"] = username

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.secret import Secret

        d = dict(src_dict)
        channel = d.pop("channel")

        secret = Secret.from_dict(d.pop("secret"))

        text = d.pop("text")

        workspace_name = d.pop("workspace_name")

        def _parse_icon_emoji(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        icon_emoji = _parse_icon_emoji(d.pop("icon_emoji", UNSET))

        def _parse_icon_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        icon_url = _parse_icon_url(d.pop("icon_url", UNSET))

        def _parse_thread_ts(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        thread_ts = _parse_thread_ts(d.pop("thread_ts", UNSET))

        def _parse_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        username = _parse_username(d.pop("username", UNSET))

        chat_request = cls(
            channel=channel,
            secret=secret,
            text=text,
            workspace_name=workspace_name,
            icon_emoji=icon_emoji,
            icon_url=icon_url,
            thread_ts=thread_ts,
            username=username,
        )

        chat_request.additional_properties = d
        return chat_request

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
