"""FastAPI router for VCS external API endpoints.

Provides cached access to repository OWNERS files from GitHub/GitLab.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import Field
from qontract_utils.events import Event
from qontract_utils.vcs.provider_protocol import (
    CreateMergeRequestInput,
    MergeRequestFile,
)

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, EventManagerDep, SecretManagerDep
from qontract_api.external.vcs.schemas import (
    CreateMergeRequestRequest,
    CreateMergeRequestResponse,
    FindMergeRequestParams,
    RepoOwnersResponse,
    VCSProvider,
)
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
        ...,
        description="Repository URL (e.g., https://github.com/owner/repo)",
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


@router.get(
    "/merge-requests",
    operation_id="vcs-find-merge-request",
)
def find_merge_request(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    params: Annotated[
        FindMergeRequestParams,
        Query(description="Find merge request query parameters"),
    ],
) -> CreateMergeRequestResponse | None:
    """Find an open merge request by source branch.

    Args:
        params: Query parameters with repo_url, source_branch, and token

    Returns:
        CreateMergeRequestResponse with the MR URL, or None if not found

    """
    client = create_vcs_workspace_client(
        repo_url=params.repo_url,
        token=secret_manager.read(params),
        cache=cache,
        settings=settings,
    )

    if mr_url := client.find_merge_request(params.source_branch):
        return CreateMergeRequestResponse(url=mr_url)
    return None


@router.post(
    "/merge-requests",
    operation_id="vcs-create-merge-request",
    status_code=201,
)
def create_merge_request(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    event_manager: EventManagerDep,
    request: CreateMergeRequestRequest,
) -> CreateMergeRequestResponse:
    """Create a merge request with file changes in a VCS repository.

    Creates a new branch, applies file operations (create/update/delete),
    and opens a merge request against the target branch.

    Callers should use ``GET /merge-requests`` to check for existing MRs
    before calling this endpoint to avoid duplicate creation.

    Args:
        request: Merge request details including repo, auth, and file operations

    Returns:
        CreateMergeRequestResponse with the URL of the created merge request

    """
    logger.info(
        f"Creating merge request in {request.repo_url}",
        repo_url=request.repo_url,
        title=request.title,
        source_branch=request.source_branch,
    )

    client = create_vcs_workspace_client(
        repo_url=request.repo_url,
        token=secret_manager.read(request.token),
        cache=cache,
        settings=settings,
    )

    mr_url = client.create_merge_request(
        CreateMergeRequestInput(
            title=request.title,
            description=request.description,
            source_branch=request.source_branch,
            target_branch=request.target_branch,
            file_operations=[
                MergeRequestFile(
                    path=op.path,
                    content=op.content,
                    commit_message=op.commit_message,
                )
                for op in request.file_operations
            ],
            labels=request.labels,
            auto_merge=request.auto_merge,
        ),
    )

    logger.info(
        "Merge request created: %s",
        mr_url,
        repo_url=request.repo_url,
        mr_url=mr_url,
    )

    if event_manager:
        event_manager.publish_event(
            Event(
                source=__name__,
                type="qontract-api.vcs.create-merge-request",
                data={
                    "repo_url": request.repo_url,
                    "url": mr_url,
                    "title": request.title,
                    "source_branch": request.source_branch,
                },
                datacontenttype="application/json",
            ),
        )

    return CreateMergeRequestResponse(url=mr_url)
