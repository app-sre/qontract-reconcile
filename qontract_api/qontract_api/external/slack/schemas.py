"""API schemas for Slack external chat endpoint."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from qontract_api.models import Secret, TaskResult, TaskStatus


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
    resolve_mentions: bool = Field(
        default=False,
        description=(
            "If true, resolve '@handle' tokens in `text` to real Slack mentions "
            "(usergroup or user). Leave false for free text that should be "
            "posted literally — only set true when the caller intentionally "
            "constructs a handle to ping."
        ),
    )

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Exactly one of 'channel' or 'user' must be set."""
        if bool(self.channel) == bool(self.user):
            raise ValueError("Exactly one of 'channel' or 'user' must be set")
        return self


class ChatTaskResponse(BaseModel, frozen=True):
    """Response model for POST /chat.

    Returned immediately when the send is queued. Contains task_id and
    status_url for retrieving the result via GET request (see ADR-003).
    """

    id: str = Field(..., description="Task ID")
    status: TaskStatus = Field(
        default=TaskStatus.PENDING,
        description="Task status (always 'pending' initially)",
    )
    status_url: str = Field(
        ..., description="URL to retrieve task result (GET request)"
    )


class ChatTaskResult(TaskResult, frozen=True):
    """Result model for the chat-post-message background task.

    Returned by GET /chat/{task_id}.
    """

    actions: list[str] = Field(
        default=[],
        description=(
            "Unused for this task — present only to satisfy the shared "
            "task-result protocol."
        ),
    )
    ts: str | None = Field(
        default=None, description="Message timestamp (set on success)"
    )
    channel: str | None = Field(
        default=None,
        description="Channel ID where the message was posted (set on success)",
    )
    thread_ts: str | None = Field(
        default=None,
        description="Thread timestamp if this was a threaded reply (set on success)",
    )
