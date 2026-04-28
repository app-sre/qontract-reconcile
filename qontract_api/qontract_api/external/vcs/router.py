"""FastAPI router for VCS external API endpoints.

Provides cached access to repository OWNERS files from GitHub/GitLab,
file reading, and file sync reconciliation.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import Field
from qontract_utils.events import Event

from qontract_api.config import settings
from qontract_api.dependencies import (
    CacheDep,
    EventManagerDep,
    SecretManagerDep,
    UserDep,
)
from qontract_api.external.vcs.file_sync_service import FileSyncService
from qontract_api.external.vcs.schemas import (
    FileSyncRequest,
    FileSyncResponse,
    FileSyncStatus,
    GetFileParams,
    GetFileResponse,
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
        ..., description="Repository URL (e.g., https://github.com/owner/repo)"
    )
    owners_file: str = Field(
        "/OWNERS",
        description="Path to OWNERS file in the repository (e.g., /OWNERS or /path/to/OWNERS)",
    )

    ref: str = Field(..., description="Git reference (branch, tag, commit SHA)")


@router.get(
    "/repos/owners",
    operation_id="vcs-repo-owners",
)
def get_repo_owners(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    _user: UserDep,
    params: Annotated[
        VCSQueryParams,
        Query(description="VCS repository query parameters"),
    ],
) -> RepoOwnersResponse:
    """Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).
    """
    logger.info(
        f"Fetching OWNERS for repository {params.repo_url}",
        url=params.repo_url,
        path=params.owners_file,
        ref=params.ref,
    )

    client = create_vcs_workspace_client(
        repo_url=params.repo_url,
        token=secret_manager.read(params),
        cache=cache,
        settings=settings,
    )

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

    return RepoOwnersResponse(
        provider=VCSProvider(client.provider_name),
        approvers=owners.approvers,
        reviewers=owners.reviewers,
    )


@router.get(
    "/repos/file",
    operation_id="vcs-get-file",
    responses={404: {"description": "File not found in the repository"}},
)
def get_file(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    _user: UserDep,
    params: Annotated[
        GetFileParams,
        Query(description="VCS file read parameters"),
    ],
) -> GetFileResponse:
    """Read a file from a VCS repository."""
    client = create_vcs_workspace_client(
        repo_url=params.repo_url,
        token=secret_manager.read(params),
        cache=cache,
        settings=settings,
    )

    if (content := client.get_file(path=params.file_path, ref=params.ref)) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {params.file_path}",
        )

    return GetFileResponse(content=content)


@router.post(
    "/file-sync",
    operation_id="vcs-file-sync",
)
def file_sync(
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    event_manager: EventManagerDep,
    _user: UserDep,
    request: FileSyncRequest,
) -> FileSyncResponse:
    """Reconcile file states in a VCS repository.

    Creates a merge request with the given file operations,
    deduplicating by MR title. Does not read current file state —
    relies on GitLab/GitHub for validation.
    """
    logger.info(
        f"File sync reconciliation for {request.repo_url}",
        repo_url=request.repo_url,
        title=request.title,
        operations_count=len(request.file_operations),
    )

    client = create_vcs_workspace_client(
        repo_url=request.repo_url,
        token=secret_manager.read(request.token),
        cache=cache,
        settings=settings,
    )

    service = FileSyncService(client)

    try:
        response = service.reconcile(request)
    except Exception as e:
        logger.exception(
            f"File sync failed for {request.repo_url}",
            repo_url=request.repo_url,
            title=request.title,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File sync reconciliation failed",
        ) from e

    if response.status == FileSyncStatus.MR_CREATED and event_manager:
        event_manager.publish_event(
            Event(
                source=__name__,
                type="qontract-api.vcs.file-sync",
                data={
                    "repo_url": request.repo_url,
                    "url": response.mr_url,
                    "title": request.title,
                    "status": response.status.value,
                },
                datacontenttype="application/json",
            ),
        )

    logger.info(
        f"File sync result: {response.status.value}",
        repo_url=request.repo_url,
        title=request.title,
        status=response.status.value,
        mr_url=response.mr_url,
    )

    return response
