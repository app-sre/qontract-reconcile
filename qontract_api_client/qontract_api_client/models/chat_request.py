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
    """Request model for posting a Slack message or DM.

    Exactly one of `channel` or `user` must be set:
    - `channel`: post to a Slack channel by name
    - `user`: send a DM to a user by org_username

        Attributes:
            secret (Secret): Reference to a secret stored in a secret manager.
            text (str): Message text
            workspace_name (str): Slack workspace name
            channel (None | str | Unset): Channel name to post to (e.g., 'sd-app-sre-reconcile')
            icon_emoji (None | str | Unset): Emoji to use as the message icon (e.g., ':robot_face:')
            icon_url (None | str | Unset): URL to an image to use as the message icon
            thread_ts (None | str | Unset): Optional thread timestamp for replies
            user (None | str | Unset): org_username to send a DM to (e.g., 'jsmith@redhat.com')
            username (None | str | Unset): Bot username to display
    """

    secret: Secret
    text: str
    workspace_name: str
    channel: None | str | Unset = UNSET
    icon_emoji: None | str | Unset = UNSET
    icon_url: None | str | Unset = UNSET
    thread_ts: None | str | Unset = UNSET
    user: None | str | Unset = UNSET
    username: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        secret = self.secret.to_dict()

        text = self.text

        workspace_name = self.workspace_name

        channel: None | str | Unset
        if isinstance(self.channel, Unset):
            channel = UNSET
        else:
            channel = self.channel

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

        user: None | str | Unset
        if isinstance(self.user, Unset):
            user = UNSET
        else:
            user = self.user

        username: None | str | Unset
        if isinstance(self.username, Unset):
            username = UNSET
        else:
            username = self.username

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "secret": secret,
            "text": text,
            "workspace_name": workspace_name,
        })
        if channel is not UNSET:
            field_dict["channel"] = channel
        if icon_emoji is not UNSET:
            field_dict["icon_emoji"] = icon_emoji
        if icon_url is not UNSET:
            field_dict["icon_url"] = icon_url
        if thread_ts is not UNSET:
            field_dict["thread_ts"] = thread_ts
        if user is not UNSET:
            field_dict["user"] = user
        if username is not UNSET:
            field_dict["username"] = username

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.secret import Secret

        d = dict(src_dict)
        secret = Secret.from_dict(d.pop("secret"))

        text = d.pop("text")

        workspace_name = d.pop("workspace_name")

        def _parse_channel(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        channel = _parse_channel(d.pop("channel", UNSET))

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

        def _parse_user(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        user = _parse_user(d.pop("user", UNSET))

        def _parse_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        username = _parse_username(d.pop("username", UNSET))

        chat_request = cls(
            secret=secret,
            text=text,
            workspace_name=workspace_name,
            channel=channel,
            icon_emoji=icon_emoji,
            icon_url=icon_url,
            thread_ts=thread_ts,
            user=user,
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
