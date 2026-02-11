from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel, frozen=True):
    """A generic event in the qontract system.

    Events are versioned, timestamped records of something that happened.
    They are serialized to JSON for transport via SNS/SQS.
    """

    version: int = Field(
        default=1,
        description="Event schema version for forward compatibility",
    )
    event_type: str = Field(
        ...,
        description="Dot-separated event type (e.g., 'slack-usergroups.update_users')",
    )
    source: str = Field(
        ...,
        description="Source system that produced the event (e.g., 'qontract-api')",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
        description="UTC timestamp of when the event occurred",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data payload",
    )
