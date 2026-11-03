"""FastAPI router for GitHub external API endpoints.

Provides cached, read-only access to GitHub organization membership and
GitHub account validation (see ADR-013: external calls through qontract-api).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.github.schemas import (
    GithubAccountType,
    GithubOrgMembersParams,
    GithubOrgMembersResponse,
    GithubUserInfo,
    GithubUsersValidateRequest,
    GithubUsersValidateResponse,
)
from qontract_api.github.github_client_factory import GithubClientFactory
from qontract_api.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/github",
    tags=["external"],
)


@router.get(
    "/org-members",
    operation_id="github-org-members",
)
def get_org_members(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    _user: UserDep,
    params: Annotated[
        GithubOrgMembersParams,
        Query(description="GitHub organization members query parameters"),
    ],
) -> GithubOrgMembersResponse:
    """Get all members of a GitHub organization.

    Lists every member of the organization (any role) using the GitHub API
    token resolved from Vault. Results are cached for performance (TTL
    configured in settings).
    """
    logger.info(
        f"Fetching members for GitHub org {params.org_name}",
        org=params.org_name,
    )

    client = GithubClientFactory(
        cache=cache,
        settings=settings,
    ).create_workspace_client(token=secret_manager.read(params))

    members = client.get_all_members(params.org_name)

    logger.info(
        f"Found {len(members)} members for GitHub org {params.org_name}",
        org=params.org_name,
        members_count=len(members),
    )

    return GithubOrgMembersResponse(members=members)


@router.post(
    "/users/validate",
    operation_id="github-users-validate",
)
def validate_users(
    request: GithubUsersValidateRequest,
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    _user: UserDep,
) -> GithubUsersValidateResponse:
    """Validate GitHub usernames against the GitHub API.

    Looks up each requested username via the GitHub API, using the token
    resolved from Vault. Results are cached per-username (including negative
    caching of non-existent accounts) for performance.

    Usernames that do not exist, or do not match the requested account_type,
    are omitted from the response - callers must treat a missing username as
    unresolved, not as an error. This endpoint does not know the caller's
    intent (e.g. LDAP-sourced usernames, manual input); it only validates
    existence and canonical casing, so it is reusable across any future
    GitHub username validation need.
    """
    client = GithubClientFactory(
        cache=cache,
        settings=settings,
    ).create_user_workspace_client(token=secret_manager.read(request.secret))

    supported_types = set(GithubAccountType)
    validated = [
        GithubUserInfo(login=u.login, type=GithubAccountType(u.type))
        for u in client.lookup_users(request.usernames)
        if u.type in supported_types
        and (request.account_type is None or u.type == request.account_type)
    ]

    logger.info(
        f"Validated {len(validated)}/{len(request.usernames)} GitHub usernames",
        requested=len(request.usernames),
        validated=len(validated),
    )

    return GithubUsersValidateResponse(users=validated)
