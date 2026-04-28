"""MR file operations builders for LDAP user cleanup.

Contains both the YAML manipulation functions and the async builders
that compose them into file sync operation lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from qontract_api_client.models.file_sync_create import FileSyncCreate
from qontract_api_client.models.file_sync_delete import FileSyncDelete
from qontract_api_client.models.file_sync_update import FileSyncUpdate
from qontract_utils.ruamel import create_ruamel_instance, dump_yaml

from reconcile.ldap_users_api.models import PathType, UserPaths

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

# Union type matching FileSyncRequest.file_operations
FileSyncFileOp = FileSyncCreate | FileSyncDelete | FileSyncUpdate

# --- YAML manipulation functions ---


def remove_user_from_gabi(raw_yaml: str, username: str) -> str:
    """Remove user from GABI users list.

    Removes entries from content["users"] where $ref contains the username.
    """
    yaml = create_ruamel_instance(explicit_start=True)
    content = yaml.load(raw_yaml)

    original_length = len(content["users"])
    content["users"] = [
        user for user in content["users"] if Path(user["$ref"]).stem != username
    ]

    if len(content["users"]) == original_length:
        return raw_yaml

    return dump_yaml(yaml, content)


def remove_user_from_aws_accounts(raw_yaml: str, username: str) -> str:
    """Remove user from AWS resetPasswords list.

    Removes entries from content["resetPasswords"] where user.$ref contains the username.
    """
    yaml = create_ruamel_instance(explicit_start=True)
    content = yaml.load(raw_yaml)

    original_length = len(content["resetPasswords"])
    content["resetPasswords"] = [
        record
        for record in content["resetPasswords"]
        if Path(record["user"]["$ref"]).stem != username
    ]

    if len(content["resetPasswords"]) == original_length:
        return raw_yaml

    return dump_yaml(yaml, content)


def remove_user_from_schedule(raw_yaml: str, username: str) -> str:
    """Remove user from all schedule entries.

    Removes entries from content["schedule"][*]["users"] where the $ref filename stem
    matches the username.
    """
    yaml = create_ruamel_instance(explicit_start=True)
    content = yaml.load(raw_yaml)

    modified = False
    for schedule_record in content["schedule"]:
        original_length = len(schedule_record["users"])
        schedule_record["users"] = [
            user
            for user in schedule_record["users"]
            if username != Path(user["$ref"]).stem
        ]
        if len(schedule_record["users"]) != original_length:
            modified = True

    if not modified:
        return raw_yaml

    return dump_yaml(yaml, content)


# --- YAML modifier registry ---

_YAML_MODIFIERS: dict[PathType, Callable[[str, str], str]] = {
    PathType.GABI: remove_user_from_gabi,
    PathType.AWS_ACCOUNTS: remove_user_from_aws_accounts,
    PathType.SCHEDULE: remove_user_from_schedule,
}


# --- Async file operations builders ---


async def build_app_interface_file_operations(
    *,
    user: UserPaths,
    vcs_get_file: Callable[..., Awaitable[str | None]],
    commit_message: str,
) -> list[FileSyncFileOp]:
    """Build file operations for deleting a user from app-interface.

    Args:
        user: User paths to process
        vcs_get_file: Async function to read file content (path kwarg)
        commit_message: Commit message for all operations

    Returns:
        List of file operations (deletes + modifications)
    """
    operations: list[FileSyncFileOp] = [
        FileSyncDelete(
            path=path_spec.path,
            commit_message=commit_message,
        )
        for path_spec in user.delete_file_paths
    ]

    for path_spec in user.modify_file_paths:
        if (raw_yaml := await vcs_get_file(path=path_spec.path)) is None:
            continue

        modifier = _YAML_MODIFIERS[path_spec.type]
        modified_yaml = modifier(raw_yaml, user.username)

        if modified_yaml != raw_yaml:
            operations.append(
                FileSyncUpdate(
                    path=path_spec.path,
                    content=modified_yaml,
                    commit_message=commit_message,
                )
            )

    return operations


# Known field names that identify a user entry's username
_USER_NAME_FIELDS = ("name", "login_name")


def _remove_users_from_infra_file(raw_yaml: str, usernames: set[str]) -> str | None:
    """Remove users from all user lists in an infra YAML file.

    Scans top-level keys for lists of dicts that have a known username field
    (name, login_name). Removes matching entries and appends to deleted_users.

    Args:
        raw_yaml: Raw YAML content
        usernames: Usernames to remove

    Returns:
        Modified YAML string, or None if no changes
    """
    yaml = create_ruamel_instance(explicit_start=True)
    content = yaml.load(raw_yaml)

    changed = False
    if "deleted_users" not in content:
        content["deleted_users"] = []

    for key, value in content.items():
        if key == "deleted_users" or not isinstance(value, list) or not value:
            continue

        # Detect the name field from the first entry
        first = value[0]
        if not isinstance(first, dict):
            continue
        if not (name_field := next((f for f in _USER_NAME_FIELDS if f in first), None)):
            continue

        new_list = []
        for entry in value:
            if entry[name_field] in usernames:
                content["deleted_users"].append(entry[name_field])
                changed = True
            else:
                new_list.append(entry)
        content[key] = new_list

    if not changed:
        return None

    return dump_yaml(yaml, content)


async def build_infra_file_operations(
    *,
    usernames: Iterable[str],
    infra_paths: Iterable[str],
    vcs_get_file: Callable[..., Awaitable[str | None]],
    commit_message: str,
) -> list[FileSyncFileOp]:
    """Build file operations for deleting users from infra repo.

    Processes each file in infra_paths, scanning for user lists and
    moving matching entries to deleted_users.

    Args:
        usernames: Usernames to delete
        infra_paths: Paths to infra YAML files to process
        vcs_get_file: Async function to read file content (path kwarg)
        commit_message: Commit message for the operations

    Returns:
        List of file operations for files that had changes
    """
    usernames_set = set(usernames)
    operations: list[FileSyncFileOp] = []

    for path in infra_paths:
        if raw_yaml := await vcs_get_file(path=path):
            if modified := _remove_users_from_infra_file(raw_yaml, usernames_set):
                operations.append(
                    FileSyncUpdate(
                        path=path,
                        content=modified,
                        commit_message=commit_message,
                    )
                )

    return operations
