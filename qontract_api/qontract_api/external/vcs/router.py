"""FastAPI router for VCS external API endpoints.

Provides cached access to repository OWNERS files from GitHub/GitLab.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep
from qontract_api.external.vcs.models import RepoOwnersResponse, VCSProvider
from qontract_api.external.vcs.vcs_factory import create_vcs_workspace_client
from qontract_api.logger import get_logger
from qontract_api.models import Secret

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/vcs",
    tags=["external"],
)


class VCSQueryParams(Secret):
    """Query parameters for VCS endpoints."""

    repo_url: str = Field(
        ..., description="Repository URL (e.g., https://github.com/owner/repo)"
    )
    owners_file: str = Field(
        "/OWNERS",
        description="Path to OWNERS file in the repository (e.g., /OWNERS or /path/to/OWNERS)",
    )

    ref: str = Field("master", description="Git reference (branch, tag, commit SHA)")


@router.get(
    "/repos/owners",
    operation_id="vcs-repo-owners",
)
def get_repo_owners(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    params: Annotated[
        VCSQueryParams,
        Query(description="VCS repository query parameters"),
    ],
) -> RepoOwnersResponse:
    """Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Args:
        params: VCSQueryParams with repo_url, owners_file, ref, and secret reference

    Returns:
        RepoOwnersResponse with provider type, approvers, and reviewers lists

    Raises:
        HTTPException:
            - 500 Internal Server Error: If VCS API call fails or tokens not found

    Example:
        GET /api/v1/external/vcs/repos/owners?url=https://github.com/openshift/osdctl&path=/&ref=master
        Response:
        {
            "provider": "github",
            "approvers": ["github_user1", "github_user2"],
            "reviewers": ["github_user3"]
        }
    """
    logger.info(
        f"Fetching OWNERS for repository {params.repo_url}",
        url=params.repo_url,
        path=params.owners_file,
        ref=params.ref,
    )

    # Create VCS workspace client (auto-detects GitHub/GitLab from URL)
    client = create_vcs_workspace_client(
        repo_url=params.repo_url,
        token=secret_manager.read(params),
        cache=cache,
        settings=settings,
    )

    # Fetch OWNERS data (with caching)
    owners = client.get_owners(owners_file=params.owners_file, ref=params.ref)

    logger.info(
        f"Found {len(owners.approvers)} approvers and {len(owners.reviewers)} reviewers for {params.repo_url}",
        url=params.repo_url,
        path=params.owners_file,
        ref=params.ref,
        vcs_type=client.provider_name,
        approvers_count=len(owners.approvers),
        reviewers_count=len(owners.reviewers),
    )

    # Return immutable response model (ADR-012)
    # Provider type is needed for username translation (github_username vs org_username)
    return RepoOwnersResponse(
        provider=VCSProvider(client.provider_name),
        approvers=owners.approvers,
        reviewers=owners.reviewers,
    )
