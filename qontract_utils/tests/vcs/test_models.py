"""Tests for VCS Pydantic models."""

import pytest
from pydantic import ValidationError
from qontract_utils.vcs.models import RepoOwners, RepoTreeItem


def test_repo_tree_item_creation() -> None:
    """Test creating RepoTreeItem with required fields."""
    item = RepoTreeItem(path="src/main.py", type="blob", sha="abc123")
    assert item.path == "src/main.py"
    assert item.type == "blob"
    assert item.sha == "abc123"


def test_repo_tree_item_default_sha() -> None:
    """Test RepoTreeItem with default empty SHA."""
    item = RepoTreeItem(path="docs/", type="tree")
    assert item.path == "docs/"
    assert item.type == "tree"
    assert not item.sha


def test_repo_tree_item_immutable() -> None:
    """Test that RepoTreeItem is immutable (frozen)."""
    item = RepoTreeItem(path="src/main.py", type="blob")
    with pytest.raises(ValidationError):
        item.path = "different/path.py"  # type: ignore[misc]


def test_repo_owners_creation() -> None:
    """Test creating RepoOwners with approvers and reviewers."""
    owners = RepoOwners(
        approvers=["alice", "bob"],
        reviewers=["charlie"],
    )
    assert owners.approvers == ["alice", "bob"]
    assert owners.reviewers == ["charlie"]


def test_repo_owners_empty_lists() -> None:
    """Test RepoOwners with default empty lists."""
    owners = RepoOwners()
    assert owners.approvers == []
    assert owners.reviewers == []


def test_repo_owners_immutable() -> None:
    """Test that RepoOwners is immutable (frozen)."""
    owners = RepoOwners(approvers=["alice"])
    with pytest.raises(ValidationError):
        owners.approvers = ["bob"]  # type: ignore[misc]


def test_repo_owners_list_immutability() -> None:
    """Test that RepoOwners is frozen and cannot be modified."""
    owners = RepoOwners(approvers=["alice"])
    # Frozen models cannot have attributes reassigned
    with pytest.raises(ValidationError):
        owners.approvers = ["bob"]  # type: ignore[misc]
