"""Pydantic models for Quay API responses.

Following ADR-012 (Fully Typed Pydantic Models Over Nested Dicts):
- All models use Pydantic BaseModel with frozen=True
- Only fields consumed by integrations are declared
"""

from pydantic import BaseModel, ConfigDict, Field


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


class RobotAccount(BaseModel):
    """A Quay organization robot account (short name, without org prefix)."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    teams: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()


class RobotAccountRepository(BaseModel):
    """Repository referenced by a robot permission."""

    model_config = ConfigDict(frozen=True)

    name: str


class RobotAccountPermission(BaseModel):
    """A robot's role on a repository."""

    model_config = ConfigDict(frozen=True)

    repository: RobotAccountRepository
    role: str


class QuayRobotTeamRef(BaseModel):
    """Team membership as returned by the Quay robots list API."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str


class QuayRobotListItem(BaseModel):
    """A single robot in a Quay list-robots response."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    description: str | None = None
    teams: list[QuayRobotTeamRef] = Field(default_factory=list)
    repositories: list[str] = Field(default_factory=list)


class QuayRobotListResponse(BaseModel):
    """Envelope for GET /organization/{org}/robots."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    robots: list[QuayRobotListItem]


class QuayRobotPermissionsResponse(BaseModel):
    """Envelope for GET /organization/{org}/robots/{name}/permissions."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    permissions: list[RobotAccountPermission]


class QuayCreateRobotRequest(BaseModel):
    """PUT body for creating a robot account."""

    model_config = ConfigDict(frozen=True)

    description: str


class QuayRepoPermissionRequest(BaseModel):
    """PUT body for setting a robot's repository role."""

    model_config = ConfigDict(frozen=True)

    role: str
