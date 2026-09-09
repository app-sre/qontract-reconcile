"""FastAPI router for GitHub organization external API endpoints.

Provides cached, read-only access to GitHub organization membership
(see ADR-013: external calls through qontract-api).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.github_org.schemas import (
    GithubOrgMembersParams,
    GithubOrgMembersResponse,
)
from qontract_api.github.github_org_client_factory import GithubOrgClientFactory
from qontract_api.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/github-org",
    tags=["external"],
)


@router.get(
    "/members",
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

    client = GithubOrgClientFactory(
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
