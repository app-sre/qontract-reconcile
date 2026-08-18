"""Unit tests for create_quay_workspace_client factory function."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from qontract_api.models import Secret
from qontract_api.quay.quay_client_factory import create_quay_workspace_client
from qontract_api.quay.quay_workspace_client import QuayWorkspaceClient

if TYPE_CHECKING:
    from qontract_api.config import Settings

_SECRET = Secret(
    secret_manager_url="https://vault.example.com",
    path="secret/quay/quay.io/myorg",
)


@pytest.fixture
def mock_quay_api_cls() -> MagicMock:
    with patch("qontract_api.quay.quay_client_factory.QuayApi") as mock_cls:
        instance = MagicMock()
        instance.org = "myorg"
        mock_cls.return_value = instance
        yield mock_cls


def test_factory_resolves_secret(
    mock_quay_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.read.return_value = "test-token"

    create_quay_workspace_client(
        secret=_SECRET,
        org_name="myorg",
        base_url="https://quay.io",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    mock_secret_manager.read.assert_called_once_with(_SECRET)


def test_factory_returns_workspace_client(
    mock_quay_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.read.return_value = "test-token"

    client = create_quay_workspace_client(
        secret=_SECRET,
        org_name="myorg",
        base_url="https://quay.io",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    assert isinstance(client, QuayWorkspaceClient)
    assert client.cache is mock_cache
    assert client.settings is mock_settings


def test_factory_wires_correct_org(
    mock_quay_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.read.return_value = "test-token"

    create_quay_workspace_client(
        secret=_SECRET,
        org_name="myorg",
        base_url="https://quay.io",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    mock_quay_api_cls.assert_called_once_with(
        org="myorg", token="test-token", base_url="https://quay.io"
    )


def test_factory_cache_key_uses_base_url(
    mock_quay_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.read.return_value = "test-token"

    client = create_quay_workspace_client(
        secret=_SECRET,
        org_name="myorg",
        base_url="https://quay.example.com",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    assert "quay.example.com" in client._cache_key_repos()
