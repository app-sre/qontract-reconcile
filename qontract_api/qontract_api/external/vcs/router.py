"""FastAPI router for VCS external API endpoints.

Provides cached access to repository OWNERS files from GitHub/GitLab.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep
from qontract_api.external.vcs.models import RepoOwnersResponse, VCSProvider
from qontract_api.external.vcs.vcs_factory import create_vcs_workspace_client
from qontract_api.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/vcs",
    tags=["external"],
)


@router.get(
    "/repos/owners",
    operation_id="vcs-repo-owners",
)
def get_repo_owners(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    url: Annotated[
        str,
        Query(description="Repository URL (e.g., https://github.com/owner/repo)"),
    ],
    path: Annotated[
        str,
        Query(
            description=(
                "Path mode: '/' (root OWNERS), '/path' (specific path with inheritance)"
            )
        ),
    ] = "/",
    ref: Annotated[
        str,
        Query(description="Git reference (branch, tag, commit SHA)"),
    ] = "master",
) -> RepoOwnersResponse:
    """Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).

    Path modes:
    - "/" - Root OWNERS file only
    - "/path" - Specific path with inherited owners from parent directories

    Args:
        cache: Cache backend for VCS API responses
        url: Repository URL (e.g., https://github.com/openshift/osdctl)
        path: Path mode (/, /path, or ALL)
        ref: Git reference (branch, tag, commit SHA)

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
    logger.info(f"Fetching OWNERS for repository {url}", url=url, path=path, ref=ref)

    # Create VCS workspace client (auto-detects GitHub/GitLab from URL)
    client = create_vcs_workspace_client(
        repo_url=url,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    # Fetch OWNERS data (with caching)
    owners = client.get_owners(path=path, ref=ref)

    logger.info(
        f"Found {len(owners.approvers)} approvers and {len(owners.reviewers)} reviewers for {url}",
        url=url,
        path=path,
        ref=ref,
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
