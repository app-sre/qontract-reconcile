"""Tests for MR file operations builders."""

from unittest.mock import AsyncMock

import pytest
from qontract_api_client.models.file_sync_delete import FileSyncDelete
from qontract_api_client.models.file_sync_update import FileSyncUpdate

from reconcile.ldap_users_api.models import PathSpec, PathType, UserPaths
from reconcile.ldap_users_api.mr_builder import (
    build_app_interface_file_operations,
    build_infra_file_operations,
)

INFRA_PLAYBOOK_PATH = "ansible/hosts/host_vars/bastion.ci.int.devshift.net"
INFRA_ADMINS_PATH = "ansible/hosts/group_vars/all"

INFRA_PLAYBOOK = """---
users:
- name: alice
  key: ssh-rsa AAAA...
- name: bob
  key: ssh-rsa BBBB...
deleted_users:
- old_user
"""

GABI_FILE = """---
users:
- $ref: /access/users/alice.yml
- $ref: /access/users/bob.yml
"""

AWS_ACCOUNTS_FILE = """---
resetPasswords:
- user:
    $ref: /access/users/alice.yml
  resetPassword: true
- user:
    $ref: /access/users/bob.yml
  resetPassword: true
"""

SCHEDULE_FILE = """---
schedule:
- name: week1
  users:
  - $ref: /access/users/alice.yml
  - $ref: /access/users/bob.yml
- name: week2
  users:
  - $ref: /access/users/charlie.yml
"""


@pytest.mark.asyncio
async def test_build_delete_only_operations() -> None:
    """Test building delete operations for USER+REQUEST paths."""
    user = UserPaths(
        username="alice",
        paths=[
            PathSpec(type=PathType.USER, path="/access/users/alice.yml"),
            PathSpec(type=PathType.REQUEST, path="/access/requests/alice-request.yml"),
        ],
    )
    vcs_get_file = AsyncMock()

    ops = await build_app_interface_file_operations(
        user=user,
        vcs_get_file=vcs_get_file,
        commit_message="Remove user alice",
    )

    assert len(ops) == 2
    assert all(isinstance(op, FileSyncDelete) for op in ops)
    assert {op.path for op in ops} == {
        "data/access/users/alice.yml",
        "data/access/requests/alice-request.yml",
    }
    assert all(op.commit_message == "Remove user alice" for op in ops)
    vcs_get_file.assert_not_called()


@pytest.mark.asyncio
async def test_build_gabi_modification() -> None:
    """Test building modification operation for GABI path."""
    user = UserPaths(
        username="alice",
        paths=[
            PathSpec(type=PathType.GABI, path="/services/gabi/users.yml"),
        ],
    )
    vcs_get_file = AsyncMock(return_value=GABI_FILE)

    ops = await build_app_interface_file_operations(
        user=user,
        vcs_get_file=vcs_get_file,
        commit_message="Remove user alice",
    )

    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, FileSyncUpdate)
    assert op.path == "data/services/gabi/users.yml"
    assert "/access/users/alice.yml" not in op.content
    assert "/access/users/bob.yml" in op.content
    assert op.commit_message == "Remove user alice"
    vcs_get_file.assert_called_once_with(path="data/services/gabi/users.yml")


@pytest.mark.asyncio
async def test_build_mixed_operations() -> None:
    """Test building mixed delete and modify operations."""
    user = UserPaths(
        username="alice",
        paths=[
            PathSpec(type=PathType.USER, path="/access/users/alice.yml"),
            PathSpec(type=PathType.GABI, path="/services/gabi/users.yml"),
        ],
    )
    vcs_get_file = AsyncMock(return_value=GABI_FILE)

    ops = await build_app_interface_file_operations(
        user=user,
        vcs_get_file=vcs_get_file,
        commit_message="Remove user alice",
    )

    assert len(ops) == 2
    delete_ops = [op for op in ops if isinstance(op, FileSyncDelete)]
    modify_ops = [op for op in ops if isinstance(op, FileSyncUpdate)]

    assert len(delete_ops) == 1
    assert delete_ops[0].path == "data/access/users/alice.yml"

    assert len(modify_ops) == 1
    assert modify_ops[0].path == "data/services/gabi/users.yml"
    assert "/access/users/bob.yml" in modify_ops[0].content

    vcs_get_file.assert_called_once_with(path="data/services/gabi/users.yml")


@pytest.mark.asyncio
async def test_build_aws_accounts_modification() -> None:
    """Test building modification operation for AWS_ACCOUNTS path."""
    user = UserPaths(
        username="alice",
        paths=[
            PathSpec(
                type=PathType.AWS_ACCOUNTS,
                path="/aws/accounts/account-foo.yml",
            ),
        ],
    )
    vcs_get_file = AsyncMock(return_value=AWS_ACCOUNTS_FILE)

    ops = await build_app_interface_file_operations(
        user=user,
        vcs_get_file=vcs_get_file,
        commit_message="Remove user alice",
    )

    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, FileSyncUpdate)
    assert op.path == "data/aws/accounts/account-foo.yml"
    assert "/access/users/alice.yml" not in op.content
    assert "/access/users/bob.yml" in op.content
    vcs_get_file.assert_called_once_with(path="data/aws/accounts/account-foo.yml")


@pytest.mark.asyncio
async def test_build_schedule_modification() -> None:
    """Test building modification operation for SCHEDULE path."""
    user = UserPaths(
        username="alice",
        paths=[
            PathSpec(type=PathType.SCHEDULE, path="/services/schedule.yml"),
        ],
    )
    vcs_get_file = AsyncMock(return_value=SCHEDULE_FILE)

    ops = await build_app_interface_file_operations(
        user=user,
        vcs_get_file=vcs_get_file,
        commit_message="Remove user alice",
    )

    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, FileSyncUpdate)
    assert op.path == "data/services/schedule.yml"
    assert "/access/users/alice.yml" not in op.content
    assert "/access/users/bob.yml" in op.content
    assert "/access/users/charlie.yml" in op.content
    vcs_get_file.assert_called_once_with(path="data/services/schedule.yml")


@pytest.mark.asyncio
async def test_build_no_changes() -> None:
    """Test building operations when file has no matching user."""
    user = UserPaths(
        username="nonexistent",
        paths=[
            PathSpec(type=PathType.GABI, path="/services/gabi/users.yml"),
        ],
    )
    vcs_get_file = AsyncMock(return_value=GABI_FILE)

    ops = await build_app_interface_file_operations(
        user=user,
        vcs_get_file=vcs_get_file,
        commit_message="Remove user nonexistent",
    )

    # No changes, so no operations
    assert len(ops) == 0
    vcs_get_file.assert_called_once_with(path="data/services/gabi/users.yml")


INFRA_ADMINS = """---
admins_list:
- login_name: alice
  full_name: Alice Smith
  sudo_right: true
  ssh_pub_key:
  - ssh-ed25519 AAAA...
- login_name: bob
  full_name: Bob Jones
  sudo_right: true
  ssh_pub_key:
  - ssh-ed25519 BBBB...
deleted_users:
- old_admin
"""


@pytest.mark.asyncio
async def test_build_infra_operations_playbook_only() -> None:
    """Test infra operations - user in bastion playbook only."""

    async def mock_get_file(*, path: str) -> str | None:  # noqa: RUF029
        if path == INFRA_PLAYBOOK_PATH:
            return INFRA_PLAYBOOK
        if path == INFRA_ADMINS_PATH:
            return INFRA_ADMINS
        return None

    ops = await build_infra_file_operations(
        usernames=["alice"],
        infra_paths=[INFRA_PLAYBOOK_PATH, INFRA_ADMINS_PATH],
        vcs_get_file=mock_get_file,
        commit_message="Remove user alice",
    )

    # alice is in both files
    assert len(ops) == 2
    paths = {op.path for op in ops}
    assert INFRA_PLAYBOOK_PATH in paths
    assert INFRA_ADMINS_PATH in paths

    # Check bastion file
    bastion_op = next(op for op in ops if op.path == INFRA_PLAYBOOK_PATH)
    assert isinstance(bastion_op, FileSyncUpdate)
    deleted_section = bastion_op.content.split("deleted_users:")[1]
    assert "alice" in deleted_section

    # Check admins file
    admins_op = next(op for op in ops if op.path == INFRA_ADMINS_PATH)
    assert isinstance(admins_op, FileSyncUpdate)
    deleted_section = admins_op.content.split("deleted_users:")[1]
    assert "alice" in deleted_section
    assert "bob" in admins_op.content.split("deleted_users:")[0]


@pytest.mark.asyncio
async def test_build_infra_operations_no_match() -> None:
    """Test infra operations when user doesn't exist in either file."""

    async def mock_get_file(*, path: str) -> str | None:  # noqa: RUF029
        if path == INFRA_PLAYBOOK_PATH:
            return INFRA_PLAYBOOK
        if path == INFRA_ADMINS_PATH:
            return INFRA_ADMINS
        return None

    ops = await build_infra_file_operations(
        usernames=["nonexistent"],
        infra_paths=[INFRA_PLAYBOOK_PATH, INFRA_ADMINS_PATH],
        vcs_get_file=mock_get_file,
        commit_message="Remove user nonexistent",
    )

    assert len(ops) == 0


@pytest.mark.asyncio
async def test_build_infra_operations_admins_only() -> None:
    """Test infra operations - user only in admins_list, not bastion."""
    admins_only = """---
admins_list:
- login_name: charlie
  full_name: Charlie Admin
  sudo_right: true
  ssh_pub_key:
  - ssh-ed25519 CCCC...
deleted_users: []
"""

    async def mock_get_file(*, path: str) -> str | None:  # noqa: RUF029
        if path == INFRA_PLAYBOOK_PATH:
            return INFRA_PLAYBOOK
        if path == INFRA_ADMINS_PATH:
            return admins_only
        return None

    ops = await build_infra_file_operations(
        usernames=["charlie"],
        infra_paths=[INFRA_PLAYBOOK_PATH, INFRA_ADMINS_PATH],
        vcs_get_file=mock_get_file,
        commit_message="Remove user charlie",
    )

    # charlie is only in admins, not in bastion
    assert len(ops) == 1
    assert ops[0].path == INFRA_ADMINS_PATH
