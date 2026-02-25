"""API models for Slack external chat endpoint."""

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class ChatRequest(BaseModel, frozen=True):
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
    """

    workspace_name: str = Field(
        ...,
        description="Slack workspace name",
    )
    channel: str = Field(
        ...,
        description="Channel name to post to (e.g., 'sd-app-sre-reconcile')",
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
