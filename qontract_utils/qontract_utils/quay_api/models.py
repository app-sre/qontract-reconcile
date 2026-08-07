"""Pydantic models for Quay API responses.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel with frozen=True
- Only fields consumed by integrations are declared
"""

from pydantic import BaseModel, Field


class QuayRepo(BaseModel, frozen=True):
    """Quay repository as returned by the list repositories API.

    Attributes:
        name: Repository name
        is_public: Whether the repository is publicly visible
        description: Repository description
    """

    name: str = Field(..., description="Repository name")
    is_public: bool = Field(..., description="Whether the repository is public")
    description: str = Field(default="", description="Repository description")
