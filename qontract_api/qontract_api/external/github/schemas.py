"""API schemas for the GitHub external integration."""

from enum import StrEnum

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class GithubOrgMembersParams(Secret):
    """Query parameters for the GitHub org members endpoint.

    Inherits the Vault secret reference fields (secret_manager_url, path,
    field, version) from Secret; the referenced secret holds the GitHub API
    token used to list organization members.
    """

    org_name: str = Field(..., description="GitHub organization name")


class GithubOrgMembersResponse(BaseModel, frozen=True):
    """Response with all members of a GitHub organization."""

    members: list[str] = Field(
        ...,
        description="GitHub usernames (original case) of all organization members",
    )


class GithubAccountType(StrEnum):
    """GitHub account entity type, as reported by the GitHub API.

    Known values the GitHub users API returns for `GET /users/{username}`.
    Any other value (GitHub could introduce new account types) is treated as
    unsupported and skipped rather than raised - see validate_users in router.py.
    """

    USER = "User"
    ORGANIZATION = "Organization"
    BOT = "Bot"


class GithubUsersValidateRequest(BaseModel, frozen=True):
    """Request to validate GitHub usernames against the GitHub API."""

    secret: Secret = Field(
        ..., description="Vault secret reference for the GitHub API token"
    )
    usernames: list[str] = Field(..., description="GitHub usernames to validate")
    account_type: GithubAccountType | None = Field(
        None,
        description=(
            "If set, only accounts of this type are returned; accounts of "
            "another type are treated as not found. If unset, all existing "
            "accounts are returned regardless of type."
        ),
    )


class GithubUserInfo(BaseModel, frozen=True):
    """A validated GitHub account."""

    login: str = Field(..., description="Canonical login, as returned by GitHub")
    type: GithubAccountType = Field(..., description="Account entity type")


class GithubUsersValidateResponse(BaseModel, frozen=True):
    """Response with validated GitHub accounts.

    Usernames that do not exist, or do not match the requested account_type,
    are omitted from the response - callers must treat a missing username as
    unresolved, not as an error.
    """

    users: list[GithubUserInfo] = Field(..., description="Validated GitHub accounts")
