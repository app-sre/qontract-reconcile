"""Pydantic models for Slack API data structures."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SlackUserProfile(BaseModel, frozen=True):
    """Slack user profile data."""

    email: str | None = None
    real_name: str | None = None
    display_name: str | None = None


class SlackEnterpriseUser(BaseModel, frozen=True):
    """Slack enterprise user data."""

    id: str


class SlackUser(BaseModel, frozen=True, serialize_by_alias=True):
    """Slack user data."""

    pk: str = Field(..., description="Slack user ID", alias="id")
    name: str = ""
    deleted: bool = False
    profile: SlackUserProfile
    enterprise_user: SlackEnterpriseUser | None = None

    @property
    def org_username(self) -> str:
        return self.profile.email.split("@")[0] if self.profile.email else self.name

    @property
    def id(self) -> str:
        return self.enterprise_user.id if self.enterprise_user else self.pk


class SlackUsergroupPrefs(BaseModel, frozen=True):
    """Slack usergroup preferences."""

    channels: list[str] = Field(
        default_factory=list,
        description="List of channel IDs",
    )


class SlackUsergroup(BaseModel, frozen=True):
    """Slack usergroup data."""

    id: str
    handle: str
    name: str = ""
    description: str = ""
    users: list[str] = Field(default_factory=list, description="List of user IDs")
    prefs: SlackUsergroupPrefs = Field(default_factory=SlackUsergroupPrefs)
    date_delete: int = 0

    def is_active(self) -> bool:
        return self.date_delete == 0


class SlackChannel(BaseModel, frozen=True):
    """Slack channel data."""

    id: str
    name: str
    is_archived: bool = False
    is_member: bool = False


class ChatPostMessageResponse(BaseModel, frozen=True):
    """Response from chat.postMessage Slack API call."""

    ts: str
    channel: str
    thread_ts: str | None = None


class SlackMessageReaction(BaseModel, frozen=True):
    """A reaction (emoji) on a Slack message."""

    name: str
    count: int = 0


class SlackMessageAttachment(BaseModel, frozen=True):
    """A legacy attachment on a Slack message (e.g. alertmanager notifications)."""

    title: str | None = None
    text: str | None = None


class SlackMessage(BaseModel, frozen=True):
    """A message returned by conversations.history."""

    ts: str
    text: str = ""
    subtype: str | None = None
    username: str | None = None
    reply_count: int = 0
    reactions: list[SlackMessageReaction] = Field(default_factory=list)
    attachments: list[SlackMessageAttachment] = Field(default_factory=list)
