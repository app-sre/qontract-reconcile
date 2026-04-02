"""Tests for AWSWorkspaceClient access key caching and support case fallback."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.aws_api_typed.iam import AWSAccessKey, AWSLimitExceededError

from qontract_api.aws.aws_workspace_client import AWSWorkspaceClient


@pytest.fixture
def mock_aws_api() -> MagicMock:
    """Create mock AWSApi."""
    return MagicMock()


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock CacheBackend."""
    cache = MagicMock()
    cache.get.return_value = None  # Default: cache miss
    cache.lock.return_value.__enter__ = MagicMock()
    cache.lock.return_value.__exit__ = MagicMock(return_value=False)
    return cache


@pytest.fixture
def client(mock_aws_api: MagicMock, mock_cache: MagicMock) -> AWSWorkspaceClient:
    """Create workspace client with mocks."""
    return AWSWorkspaceClient(
        aws_api=mock_aws_api,
        cache=mock_cache,
        settings=MagicMock(),
    )


# --- Access key caching tests ---


def test_create_access_key_caches_result(
    client: AWSWorkspaceClient,
    mock_aws_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """Access key creation should be cached to prevent duplicate keys on retry."""
    mock_key = AWSAccessKey(AccessKeyId="AKIATEST", SecretAccessKey="secret123")
    mock_aws_api.iam.create_access_key.return_value = mock_key

    result = client.create_access_key(account_name="my-account", user_name="terraform")

    assert result.access_key_id == "AKIATEST"
    assert result.secret_access_key == "secret123"
    mock_cache.set.assert_called()


def test_create_access_key_returns_cached_on_hit(
    client: AWSWorkspaceClient,
    mock_aws_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """If access key is cached, return it without calling AWS."""
    mock_cache.get.return_value = (
        '{"access_key_id": "AKIACACHED", "secret_access_key": "cached123"}'
    )

    result = client.create_access_key(account_name="my-account", user_name="terraform")

    assert result.access_key_id == "AKIACACHED"
    assert result.secret_access_key == "cached123"
    mock_aws_api.iam.create_access_key.assert_not_called()


def test_create_access_key_raises_on_max_keys(
    client: AWSWorkspaceClient,
    mock_aws_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """If max keys reached, raise RuntimeError instead of deleting existing keys."""
    mock_aws_api.iam.create_access_key.side_effect = AWSLimitExceededError("max keys")

    with pytest.raises(
        RuntimeError,
        match="maximum number of access keys",
    ):
        client.create_access_key(account_name="my-account", user_name="terraform")

    mock_aws_api.iam.delete_access_key.assert_not_called()


# --- Support case fallback tests ---


def test_get_support_case_id_falls_back_to_aws(
    client: AWSWorkspaceClient,
    mock_aws_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """If cache is empty, check AWS for open cases to prevent duplicates."""
    mock_cache.get.return_value = None
    mock_case = MagicMock()
    mock_case.case_id = "case-123"
    mock_aws_api.support.find_open_cases.return_value = [mock_case]

    result = client.get_support_case_id("my-account", uid="111111111111")

    assert result == "case-123"
    mock_aws_api.support.find_open_cases.assert_called_once_with(
        subject_contains="Add account 111111111111 to Enterprise Support",
    )
    # Should re-cache the found case ID
    mock_cache.set.assert_called()


def test_get_support_case_id_returns_none_when_no_cases(
    client: AWSWorkspaceClient,
    mock_aws_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """If no open cases in AWS either, return None (safe to create new case)."""
    mock_cache.get.return_value = None
    mock_aws_api.support.find_open_cases.return_value = []

    result = client.get_support_case_id("my-account", uid="111111111111")

    assert result is None


def test_get_support_case_id_uses_cache_when_available(
    client: AWSWorkspaceClient,
    mock_aws_api: MagicMock,
    mock_cache: MagicMock,
) -> None:
    """If cache has case ID, return it without calling AWS."""
    mock_cache.get.return_value = "case-456"

    result = client.get_support_case_id("my-account", uid="111111111111")

    assert result == "case-456"
    mock_aws_api.support.find_open_cases.assert_not_called()
