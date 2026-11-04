"""Pydantic models for PagerDuty API.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel
- Immutable with frozen=True (thread-safe)
- Type-safe throughout
"""

from pydantic import BaseModel, Field

# PagerDuty's "no one is on-call" placeholder user has a "nobody..." email
# local part. It is never a real person and never has a matching account on
# any downstream system, so callers filter it via `is_nobody_placeholder`.
_NOBODY_PLACEHOLDER_MARKER = "nobody"


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
        """Extract username from email, with plus-addressing stripped.

        Returns:
            Username part of email, before any "+" suffix (e.g. "jsmith"
            from both "jsmith@example.com" and "jsmith+pd@example.com")
        """
        return self.email.split("@", maxsplit=1)[0].split("+", 1)[0]

    @property
    def is_nobody_placeholder(self) -> bool:
        """Whether this is PagerDuty's "no one is on-call" placeholder user."""
        return _NOBODY_PLACEHOLDER_MARKER in self.username
