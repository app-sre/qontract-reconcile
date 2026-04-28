"""File sync reconciliation service.

Reconciles file operations against a VCS repository by checking
for existing MRs (dedup) and creating a new MR if needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.vcs.provider_protocol import (
    CreateMergeRequestInput,
    FileAction,
    MergeRequestFile,
)

from qontract_api.external.vcs.schemas import (
    FileSyncCreate,
    FileSyncDelete,
    FileSyncRequest,
    FileSyncResponse,
    FileSyncStatus,
    FileSyncUpdate,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api.external.vcs.schemas import FileSyncFileOperation
    from qontract_api.external.vcs.vcs_workspace_client import VCSWorkspaceClient


class FileSyncService:
    """Reconcile file operations against a VCS repository.

    Deduplicates by MR title and creates a merge request with the
    given file operations. Does NOT read current file state — trusts
    the client's operations and relies on GitLab/GitHub for validation.
    """

    def __init__(self, client: VCSWorkspaceClient) -> None:
        self._client = client

    def reconcile(self, request: FileSyncRequest) -> FileSyncResponse:
        """Reconcile file operations against VCS.

        Returns MR_EXISTS if an MR with the same title is already open,
        otherwise creates a new MR and returns MR_CREATED.
        """
        if mr_url := self._client.find_merge_request(request.title):
            return FileSyncResponse(
                status=FileSyncStatus.MR_EXISTS,
                mr_url=mr_url,
            )

        mr_url = self._client.create_merge_request(
            CreateMergeRequestInput(
                title=request.title,
                description=request.description,
                target_branch=request.target_branch,
                file_operations=list(_to_merge_request_files(request.file_operations)),
                labels=request.labels,
                auto_merge=request.auto_merge,
            ),
        )

        return FileSyncResponse(
            status=FileSyncStatus.MR_CREATED,
            mr_url=mr_url,
        )


def _to_merge_request_files(
    operations: Iterable[FileSyncFileOperation],
) -> Iterable[MergeRequestFile]:
    """Convert schema file operations to VCS provider file operations."""
    for op in operations:
        match op:
            case FileSyncCreate():
                yield MergeRequestFile(
                    path=op.path,
                    action=FileAction.CREATE,
                    content=op.content,
                    commit_message=op.commit_message,
                )
            case FileSyncUpdate():
                yield MergeRequestFile(
                    path=op.path,
                    action=FileAction.UPDATE,
                    content=op.content,
                    commit_message=op.commit_message,
                )
            case FileSyncDelete():
                yield MergeRequestFile(
                    path=op.path,
                    action=FileAction.DELETE,
                    commit_message=op.commit_message,
                )
