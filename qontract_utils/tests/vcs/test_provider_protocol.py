"""Tests for VCS provider protocol dataclasses."""

import pytest
from qontract_utils.vcs.provider_protocol import (
    AUTO_MERGE_LABEL,
    CreateMergeRequestInput,
    FileAction,
    MergeRequestFile,
)


def test_file_action_values() -> None:
    """Test FileAction enum has all required values."""
    assert set(FileAction) == {FileAction.CREATE, FileAction.UPDATE, FileAction.DELETE}
    assert FileAction.CREATE == "create"
    assert FileAction.UPDATE == "update"
    assert FileAction.DELETE == "delete"


def test_merge_request_file_immutable() -> None:
    """Test MergeRequestFile is frozen."""
    f = MergeRequestFile(
        path="a.txt", action=FileAction.CREATE, content="data", commit_message="add a"
    )
    with pytest.raises(AttributeError):
        f.path = "b.txt"  # type: ignore[misc]


def test_merge_request_file_delete() -> None:
    """Test MergeRequestFile with DELETE action has None content."""
    f = MergeRequestFile(
        path="a.txt", action=FileAction.DELETE, commit_message="delete a"
    )
    assert f.content is None
    assert f.action == FileAction.DELETE


def test_merge_request_file_update() -> None:
    """Test MergeRequestFile with UPDATE action."""
    f = MergeRequestFile(
        path="a.txt", action=FileAction.UPDATE, content="new", commit_message="update a"
    )
    assert f.content == "new"
    assert f.action == FileAction.UPDATE


def test_create_merge_request_input_defaults() -> None:
    """Test CreateMergeRequestInput has correct defaults."""
    mr = CreateMergeRequestInput(
        title="test",
        description="desc",
    )
    assert mr.target_branch == "master"
    assert mr.file_operations == []
    assert mr.labels == []
    assert mr.auto_merge is False


def test_create_merge_request_input_with_operations() -> None:
    """Test CreateMergeRequestInput with file operations."""
    ops = [
        MergeRequestFile(
            path="a.txt", action=FileAction.CREATE, content="new", commit_message="add"
        ),
        MergeRequestFile(
            path="b.txt", action=FileAction.DELETE, commit_message="delete"
        ),
    ]
    mr = CreateMergeRequestInput(
        title="test",
        description="desc",
        target_branch="main",
        file_operations=ops,
        labels=["urgent"],
        auto_merge=True,
    )
    assert len(mr.file_operations) == 2
    assert mr.labels == ["urgent"]
    assert mr.auto_merge is True
    assert mr.target_branch == "main"


def test_create_merge_request_input_immutable() -> None:
    """Test CreateMergeRequestInput is frozen."""
    mr = CreateMergeRequestInput(
        title="test",
        description="desc",
    )
    with pytest.raises(AttributeError):
        mr.title = "changed"  # type: ignore[misc]


def test_auto_merge_label_value() -> None:
    """Test AUTO_MERGE_LABEL constant."""
    assert AUTO_MERGE_LABEL == "bot/automerge"
