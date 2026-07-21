"""API schemas for Slack external chat endpoint."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from qontract_api.models import Secret


class ChatRequest(BaseModel, frozen=True):
    """Request model for posting a Slack message or DM.

    Exactly one of `channel` or `user` must be set:
    - `channel`: post to a Slack channel by name
    - `user`: send a DM to a user by org_username
    """

    workspace_name: str = Field(
        ...,
        description="Slack workspace name",
    )
    channel: str | None = Field(
        default=None,
        description="Channel name to post to (e.g., 'sd-app-sre-reconcile')",
    )
    user: str | None = Field(
        default=None,
        description="org_username to send a DM to (e.g., 'jsmith@redhat.com')",
    )
    text: str = Field(
        ...,
        description="Message text",
    )
    thread_ts: str | None = Field(
        default=None,
        description="Optional thread timestamp for replies",
    )
    icon_emoji: str | None = Field(
        default=None,
        description="Emoji to use as the message icon (e.g., ':robot_face:')",
    )
    icon_url: str | None = Field(
        default=None,
        description="URL to an image to use as the message icon",
    )
    username: str | None = Field(
        default=None,
        description="Bot username to display",
    )
    secret: Secret = Field(
        ...,
        description="Secret reference for Slack bot token",
    )

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Exactly one of 'channel' or 'user' must be set."""
        if bool(self.channel) == bool(self.user):
            raise ValueError("Exactly one of 'channel' or 'user' must be set")
        return self


class SlackMessageReactionResponse(BaseModel, frozen=True):
    """A reaction (emoji) on a Slack message."""

    name: str = Field(..., description="Reaction emoji name (e.g., 'eyes')")
    count: int = Field(default=0, description="Number of users who reacted")


class SlackMessageAttachmentResponse(BaseModel, frozen=True):
    """A legacy attachment on a Slack message (e.g. alertmanager notifications)."""

    title: str | None = Field(default=None, description="Attachment title")
    text: str | None = Field(default=None, description="Attachment text")


class SlackMessageResponse(BaseModel, frozen=True):
    """A single message from a channel's conversation history."""

    ts: str = Field(..., description="Message timestamp")
    text: str = Field(default="", description="Message text")
    subtype: str | None = Field(default=None, description="Message subtype")
    username: str | None = Field(
        default=None, description="Bot/app username that posted the message"
    )
    reply_count: int = Field(default=0, description="Number of thread replies")
    reactions: list[SlackMessageReactionResponse] = Field(default_factory=list)
    attachments: list[SlackMessageAttachmentResponse] = Field(default_factory=list)


class SlackConversationHistoryResponse(BaseModel, frozen=True):
    """Response model for the conversation history endpoint."""

    messages: list[SlackMessageResponse] = Field(
        default_factory=list,
        description="Messages in the requested time range, newest first",
    )


class ConversationsHistoryParams(Secret):
    """Query parameters for the conversation history endpoint."""

    workspace_name: str = Field(..., description="Slack workspace name")
    channel: str = Field(..., description="Channel name (e.g., 'sd-app-sre-reconcile')")
    from_timestamp: int = Field(
        ..., description="Only return messages at or after this unix timestamp"
    )
    to_timestamp: int | None = Field(
        default=None,
        description="Only return messages at or before this unix timestamp",
    )


class ChatResponse(BaseModel, frozen=True):
    """Response model for a posted Slack message.

    Immutable model returning the Slack API response fields.

    Attributes:
        ts: Message timestamp
        channel: Channel ID where the message was posted
        thread_ts: Thread timestamp if this was a threaded reply
    """

    ts: str = Field(
        ...,
        description="Message timestamp",
    )
    channel: str = Field(
        ...,
        description="Channel ID where the message was posted",
    )
    thread_ts: str | None = Field(
        default=None,
        description="Thread timestamp if this was a threaded reply",
    )
