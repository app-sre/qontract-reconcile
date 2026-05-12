import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class Event(BaseModel):
    """CloudEvent v1.0 spec as a Pydantic model.

    Replaces the removed cloudevents.pydantic integration (cloudevents SDK v2)
    while keeping the same public API: keyword construction and attribute access.
    """

    source: str
    type: str
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    specversion: str = "1.0"
    time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: Any = None
    datacontenttype: str | None = None
    dataschema: str | None = None
    subject: str | None = None
