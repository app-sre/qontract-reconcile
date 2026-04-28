"""Tests for FileSyncService reconciliation logic."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from qontract_utils.vcs.provider_protocol import FileAction

from qontract_api.external.vcs.file_sync_service import FileSyncService
from qontract_api.external.vcs.schemas import (
    FileSyncCreate,
    FileSyncDelete,
    FileSyncRequest,
    FileSyncStatus,
    FileSyncUpdate,
)
from qontract_api.models import Secret


def _secret() -> Secret:
    return Secret(
        secret_manager_url="https://vault.example.com",
        path="secret/token",
        field="token",
    )


def _request(
    file_operations: list[FileSyncCreate | FileSyncUpdate | FileSyncDelete],
    *,
    title: str = "test-mr",
) -> FileSyncRequest:
    return FileSyncRequest(
        repo_url="https://gitlab.example.com/group/project",
        token=_secret(),
        title=title,
        description="test",
        target_branch="master",
        file_operations=file_operations,
    )


def _mock_client(
    *,
    find_mr_result: str | None = None,
    create_mr_result: str = "https://gitlab.example.com/mr/1",
) -> MagicMock:
    client = MagicMock(spec=["find_merge_request", "create_merge_request"])
    client.find_merge_request.return_value = find_mr_result
    client.create_merge_request.return_value = create_mr_result
    return client


# --- MR deduplication ---


def test_mr_exists_returns_existing_url() -> None:
    """When MR with same title exists, return MR_EXISTS with URL."""
    client = _mock_client(find_mr_result="https://gitlab.example.com/mr/42")
    service = FileSyncService(client)

    result = service.reconcile(
        _request([
            FileSyncDelete(path="data/users/alice.yml", commit_message="delete alice"),
        ])
    )

    assert result.status == FileSyncStatus.MR_EXISTS
    assert result.mr_url == "https://gitlab.example.com/mr/42"
    client.create_merge_request.assert_not_called()


# --- MR creation ---


def test_delete_creates_mr() -> None:
    """Delete operation creates MR with DELETE file action."""
    client = _mock_client()
    service = FileSyncService(client)

    result = service.reconcile(
        _request([
            FileSyncDelete(path="data/users/alice.yml", commit_message="delete alice"),
        ])
    )

    assert result.status == FileSyncStatus.MR_CREATED
    assert result.mr_url == "https://gitlab.example.com/mr/1"
    call_args = client.create_merge_request.call_args[0][0]
    assert len(call_args.file_operations) == 1
    assert call_args.file_operations[0].action == FileAction.DELETE
    assert call_args.file_operations[0].path == "data/users/alice.yml"


def test_create_creates_mr() -> None:
    """Create operation creates MR with CREATE file action."""
    client = _mock_client()
    service = FileSyncService(client)

    result = service.reconcile(
        _request([
            FileSyncCreate(
                path="data/new.yml",
                content="new: content\n",
                commit_message="create new",
            ),
        ])
    )

    assert result.status == FileSyncStatus.MR_CREATED
    call_args = client.create_merge_request.call_args[0][0]
    assert call_args.file_operations[0].action == FileAction.CREATE
    assert call_args.file_operations[0].content == "new: content\n"


def test_update_creates_mr() -> None:
    """Update operation creates MR with UPDATE file action."""
    client = _mock_client()
    service = FileSyncService(client)

    result = service.reconcile(
        _request([
            FileSyncUpdate(
                path="data/config.yml",
                content="new: content\n",
                commit_message="update config",
            ),
        ])
    )

    assert result.status == FileSyncStatus.MR_CREATED
    call_args = client.create_merge_request.call_args[0][0]
    assert call_args.file_operations[0].action == FileAction.UPDATE
    assert call_args.file_operations[0].content == "new: content\n"


def test_mixed_operations_all_passed_through() -> None:
    """All operations are passed through to MR creation."""
    client = _mock_client()
    service = FileSyncService(client)

    result = service.reconcile(
        _request([
            FileSyncDelete(path="data/users/alice.yml", commit_message="delete alice"),
            FileSyncUpdate(
                path="data/config.yml",
                content="updated\n",
                commit_message="update config",
            ),
            FileSyncCreate(
                path="data/new.yml",
                content="created\n",
                commit_message="create new",
            ),
        ])
    )

    assert result.status == FileSyncStatus.MR_CREATED
    call_args = client.create_merge_request.call_args[0][0]
    assert len(call_args.file_operations) == 3
    actions = [op.action for op in call_args.file_operations]
    assert actions == [FileAction.DELETE, FileAction.UPDATE, FileAction.CREATE]


def test_mr_passes_request_metadata() -> None:
    """MR creation passes title, description, labels, auto_merge from request."""
    client = _mock_client()
    service = FileSyncService(client)

    request = FileSyncRequest(
        repo_url="https://gitlab.example.com/group/project",
        token=_secret(),
        title="[ldap] delete alice",
        description="cleanup",
        target_branch="main",
        file_operations=[
            FileSyncDelete(path="data/users/alice.yml", commit_message="delete"),
        ],
        labels=["ldap-users"],
        auto_merge=True,
    )

    service.reconcile(request)

    call_args = client.create_merge_request.call_args[0][0]
    assert call_args.title == "[ldap] delete alice"
    assert call_args.description == "cleanup"
    assert call_args.target_branch == "main"
    assert call_args.labels == ["ldap-users"]
    assert call_args.auto_merge is True


def test_dedup_checked_before_create() -> None:
    """find_merge_request is called before create_merge_request."""
    client = _mock_client()
    service = FileSyncService(client)

    service.reconcile(
        _request(
            [FileSyncDelete(path="a.yml", commit_message="del")],
            title="my-mr-title",
        )
    )

    client.find_merge_request.assert_called_once_with("my-mr-title")
    client.create_merge_request.assert_called_once()


def test_create_mr_exception_propagates() -> None:
    """Exceptions from VCS API propagate to the caller."""
    client = _mock_client()
    client.create_merge_request.side_effect = RuntimeError("GitLab error")
    service = FileSyncService(client)

    with pytest.raises(RuntimeError, match="GitLab error"):
        service.reconcile(
            _request([
                FileSyncDelete(path="a.yml", commit_message="del"),
            ])
        )
