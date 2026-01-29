"""Pydantic models for PagerDuty API.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel
- Immutable with frozen=True (thread-safe)
- Type-safe throughout
"""

from pydantic import BaseModel, Field


class PagerDutyUser(BaseModel, frozen=True):
    """PagerDuty user data.

    This model represents a PagerDuty user with full API response data.
    The username property extracts the username from the email address.

    Attributes:
        id: PagerDuty user ID
        email: User email address
        name: User full name
        deleted_at: ISO timestamp if user was deleted, None otherwise
    """

    id: str = Field(..., description="PagerDuty user ID")
    email: str = Field(..., description="User email address")
    name: str = Field(..., description="User full name")

    @property
    def username(self) -> str:
        """Extract username from email.

        Returns:
            Username part of email (e.g., "jsmith" from "jsmith@example.com")
        """
        return self.email.split("@", maxsplit=1)[0]
