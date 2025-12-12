"""Tests for OwnersParser.get_owners() method."""

# ruff: noqa: ARG001

from unittest.mock import Mock

import pytest
from qontract_utils.vcs.models import RepoOwners
from qontract_utils.vcs.owners_parser import OwnersParser


@pytest.fixture
def mock_vcs_client() -> Mock:
    """Create mock VCS client for testing."""
    client = Mock()
    client.repo_url = "https://github.com/test/repo"
    return client


def test_get_owners_simple(mock_vcs_client: Mock) -> None:
    """Test parsing simple OWNERS file."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "OWNERS":
            return """
approvers:
  - alice
  - bob
reviewers:
  - charlie
"""
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    assert owners.approvers == ["alice", "bob"]
    assert owners.reviewers == ["charlie"]


def test_get_owners_with_path(mock_vcs_client: Mock) -> None:
    """Test parsing OWNERS file at specific path."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "src/OWNERS":
            return "approvers:\n  - src-owner"
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners(path="/src")

    assert owners.approvers == ["src-owner"]
    assert owners.reviewers == []


def test_get_owners_missing_file(mock_vcs_client: Mock) -> None:
    """Test handling missing OWNERS file."""
    mock_vcs_client.get_file.return_value = None

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    assert owners == RepoOwners(approvers=[], reviewers=[])


def test_get_owners_empty_file(mock_vcs_client: Mock) -> None:
    """Test handling empty OWNERS file."""
    mock_vcs_client.get_file.return_value = ""

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    assert owners == RepoOwners(approvers=[], reviewers=[])


def test_get_owners_invalid_yaml(mock_vcs_client: Mock) -> None:
    """Test handling non-dict OWNERS file content."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "OWNERS":
            # Valid YAML but not a dictionary
            return "- item1\n- item2"
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    assert owners == RepoOwners(approvers=[], reviewers=[])


def test_get_owners_malformed_yaml(mock_vcs_client: Mock) -> None:
    """Test handling malformed YAML in OWNERS file."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "OWNERS":
            # Invalid YAML syntax
            return "approvers:\n  - alice\n  invalid yaml: ]["
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    # Should return empty owners on parse error
    assert owners == RepoOwners(approvers=[], reviewers=[])


def test_get_owners_with_aliases(mock_vcs_client: Mock) -> None:
    """Test OWNERS file with alias resolution."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "OWNERS":
            return """
approvers:
  - platform-team
  - alice
reviewers:
  - bob
"""
        if path == "OWNERS_ALIASES":
            return """
aliases:
  platform-team:
    - user1
    - user2
"""
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    # platform-team alias should be expanded to user1, user2
    assert set(owners.approvers) == {"alice", "user1", "user2"}
    assert owners.reviewers == ["bob"]


def test_get_owners_only_approvers(mock_vcs_client: Mock) -> None:
    """Test OWNERS file with only approvers (no reviewers)."""
    mock_vcs_client.get_file.return_value = """
approvers:
  - alice
  - bob
"""
    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    assert owners.approvers == ["alice", "bob"]
    assert owners.reviewers == []


def test_get_owners_only_reviewers(mock_vcs_client: Mock) -> None:
    """Test OWNERS file with only reviewers (no approvers)."""
    mock_vcs_client.get_file.return_value = """
reviewers:
  - alice
  - bob
"""
    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    assert owners.approvers == []
    assert owners.reviewers == ["alice", "bob"]


def test_get_owners_sorts_usernames(mock_vcs_client: Mock) -> None:
    """Test that usernames are returned sorted."""
    mock_vcs_client.get_file.return_value = """
approvers:
  - zack
  - alice
  - bob
reviewers:
  - charlie
  - zebra
"""
    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    # Should be sorted alphabetically
    assert owners.approvers == ["alice", "bob", "zack"]
    assert owners.reviewers == ["charlie", "zebra"]


def test_get_owners_custom_ref(mock_vcs_client: Mock) -> None:
    """Test OwnersParser with custom git reference."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        # Verify ref is passed correctly
        assert ref == "develop"
        if path == "OWNERS":
            return "approvers:\n  - alice"
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="develop")
    owners = parser.get_owners()

    assert owners.approvers == ["alice"]


def test_get_owners_path_normalization_trailing_slash(mock_vcs_client: Mock) -> None:
    """Test that path with trailing slash is handled correctly."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "src/OWNERS":
            return "approvers:\n  - alice"
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners(path="/src/")

    assert owners.approvers == ["alice"]


def test_get_owners_path_normalization_no_slash(mock_vcs_client: Mock) -> None:
    """Test that path without leading slash is handled correctly."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "src/OWNERS":
            return "approvers:\n  - alice"
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners(path="src")

    assert owners.approvers == ["alice"]


def test_get_owners_root_path_variations(mock_vcs_client: Mock) -> None:
    """Test that different root path formats all resolve to OWNERS."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path in {"OWNERS", "./OWNERS"}:
            return "approvers:\n  - root-owner"
        if path == "OWNERS_ALIASES":
            return None
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")

    # All these should resolve to root OWNERS file
    assert parser.get_owners(path="/").approvers == ["root-owner"]
    assert parser.get_owners(path="").approvers == ["root-owner"]
    # Note: "/." becomes "./OWNERS" due to path normalization
    assert parser.get_owners(path="/.").approvers == ["root-owner"]


def test_get_owners_vcs_error(mock_vcs_client: Mock) -> None:
    """Test handling VCS client errors."""
    mock_vcs_client.get_file.side_effect = RuntimeError("VCS connection failed")

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    # Should return empty owners on error
    assert owners == RepoOwners(approvers=[], reviewers=[])


def test_get_owners_aliases_file_error(mock_vcs_client: Mock) -> None:
    """Test handling errors in OWNERS_ALIASES file."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "OWNERS":
            return "approvers:\n  - platform-team"
        if path == "OWNERS_ALIASES":
            # Invalid YAML in aliases file
            return "aliases:\n  bad yaml: ]["
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    # Should return empty owners when aliases file is broken
    assert owners == RepoOwners(approvers=[], reviewers=[])


def test_get_owners_deduplicates_after_alias_expansion(mock_vcs_client: Mock) -> None:
    """Test that duplicate usernames are handled after alias expansion."""

    def get_file_side_effect(path: str, ref: str) -> str | None:
        if path == "OWNERS":
            return """
approvers:
  - alice
  - team-a
  - team-b
"""
        if path == "OWNERS_ALIASES":
            return """
aliases:
  team-a:
    - alice
    - bob
  team-b:
    - alice
    - charlie
"""
        return None

    mock_vcs_client.get_file.side_effect = get_file_side_effect

    parser = OwnersParser(vcs_client=mock_vcs_client, ref="master")
    owners = parser.get_owners()

    # alice appears in direct list and both teams, should be deduplicated
    assert set(owners.approvers) == {"alice", "bob", "charlie"}
