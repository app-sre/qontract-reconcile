"""File operation builder for github-username-sync.

Builds the batched file operations that update `github_username` in each
affected user's app-interface YAML file as part of a single MR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_api_client.schemas import FileSyncCreate, FileSyncDelete, FileSyncUpdate
from qontract_utils.ruamel import create_ruamel_instance, dump_yaml

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from reconcile.github_username_sync.models import GithubUsernameUpdate

# Union type matching FileSyncRequest.file_operations
FileSyncFileOp = FileSyncCreate | FileSyncDelete | FileSyncUpdate


async def build_github_username_update_operations(
    *,
    updates: Sequence[GithubUsernameUpdate],
    vcs_get_file: Callable[..., Awaitable[str | None]],
    commit_message: str,
) -> list[FileSyncFileOp]:
    """Build file operations that correct github_username in each user's YAML file.

    Args:
        updates: Users whose github_username should be corrected
        vcs_get_file: Async function to read file content (path kwarg)
        commit_message: Commit message for all operations

    Returns:
        List of FileSyncUpdate operations for users whose file content actually changes
    """
    operations: list[FileSyncFileOp] = []
    for update in updates:
        if (raw_yaml := await vcs_get_file(path=update.path)) is None:
            continue

        yaml = create_ruamel_instance(explicit_start=True)
        content = yaml.load(raw_yaml)

        if content.get("github_username") == update.github_username:
            continue

        content["github_username"] = update.github_username
        operations.append(
            FileSyncUpdate(
                path=update.path,
                content=dump_yaml(yaml, content),
                commit_message=commit_message,
            )
        )

    return operations
