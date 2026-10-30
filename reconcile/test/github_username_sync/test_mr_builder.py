"""Tests for the github-username-sync MR file operations builder."""

from unittest.mock import AsyncMock

import pytest
from qontract_api_client.schemas import FileSyncUpdate

from reconcile.github_username_sync.models import GithubUsernameUpdate
from reconcile.github_username_sync.mr_builder import (
    build_github_username_update_operations,
)

ALICE_YAML = """---
$schema: /access/user-1.yml
name: Alice
org_username: alice
github_username: alice-old
"""


@pytest.mark.asyncio
async def test_build_single_update() -> None:
    """A single drifted user produces one FileSyncUpdate with the corrected value."""
    update = GithubUsernameUpdate(
        org_username="alice",
        path="/access/users/alice.yml",
        current_github_username="alice-old",
        github_username="alice-new",
    )
    vcs_get_file = AsyncMock(return_value=ALICE_YAML)

    ops = await build_github_username_update_operations(
        updates=[update],
        vcs_get_file=vcs_get_file,
        commit_message="sync github_username from LDAP",
    )

    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, FileSyncUpdate)
    assert op.path == "/access/users/alice.yml"
    assert op.commit_message == "sync github_username from LDAP"
    assert "github_username: alice-new" in op.content
    assert "name: Alice" in op.content
    assert "org_username: alice" in op.content
    vcs_get_file.assert_called_once_with(path="/access/users/alice.yml")


@pytest.mark.asyncio
async def test_build_multiple_updates() -> None:
    """Multiple drifted users each produce their own FileSyncUpdate."""
    updates = [
        GithubUsernameUpdate(
            org_username="alice",
            path="/access/users/alice.yml",
            current_github_username="alice-old",
            github_username="alice-new",
        ),
        GithubUsernameUpdate(
            org_username="bob",
            path="/access/users/bob.yml",
            current_github_username="bob-old",
            github_username="bob-new",
        ),
    ]

    async def mock_get_file(*, path: str) -> str | None:  # ruff: ignore[unused-async]
        return "---\nname: X\norg_username: x\ngithub_username: old\n"

    ops = await build_github_username_update_operations(
        updates=updates,
        vcs_get_file=mock_get_file,
        commit_message="sync github_username from LDAP",
    )

    assert len(ops) == 2
    assert all(isinstance(op, FileSyncUpdate) for op in ops)
    assert {op.path for op in ops} == {
        "/access/users/alice.yml",
        "/access/users/bob.yml",
    }
    contents = {op.path: op.content for op in ops if isinstance(op, FileSyncUpdate)}
    assert "github_username: alice-new" in contents["/access/users/alice.yml"]
    assert "github_username: bob-new" in contents["/access/users/bob.yml"]


@pytest.mark.asyncio
async def test_build_skips_missing_file() -> None:
    """A 404 (None) file is skipped without raising."""
    update = GithubUsernameUpdate(
        org_username="ghost",
        path="/access/users/ghost.yml",
        current_github_username="x",
        github_username="y",
    )
    vcs_get_file = AsyncMock(return_value=None)

    ops = await build_github_username_update_operations(
        updates=[update],
        vcs_get_file=vcs_get_file,
        commit_message="sync github_username from LDAP",
    )

    assert ops == []


@pytest.mark.asyncio
async def test_build_skips_when_content_already_matches() -> None:
    """If the file already has the proposed value, no operation is produced."""
    update = GithubUsernameUpdate(
        org_username="alice",
        path="/access/users/alice.yml",
        current_github_username="alice-old",
        github_username="alice-new",
    )
    already_updated_yaml = """---
name: Alice
org_username: alice
github_username: alice-new
"""
    vcs_get_file = AsyncMock(return_value=already_updated_yaml)

    ops = await build_github_username_update_operations(
        updates=[update],
        vcs_get_file=vcs_get_file,
        commit_message="sync github_username from LDAP",
    )

    assert ops == []


@pytest.mark.asyncio
async def test_build_empty_updates() -> None:
    """No updates produces no operations and never calls vcs_get_file."""
    vcs_get_file = AsyncMock()

    ops = await build_github_username_update_operations(
        updates=[],
        vcs_get_file=vcs_get_file,
        commit_message="sync github_username from LDAP",
    )

    assert ops == []
    vcs_get_file.assert_not_called()
