"""Unit tests for create_gitlab_workspace_client factory function."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from qontract_api.gitlab.gitlab_client_factory import create_gitlab_workspace_client
from qontract_api.gitlab.gitlab_workspace_client import GitlabWorkspaceClient
from qontract_api.models import Secret

if TYPE_CHECKING:
    from qontract_api.config import Settings

_SECRET = Secret(
    secret_manager_url="https://vault.example.com",
    path="secret/gitlab/gitlab-cee/token",
)


@pytest.fixture
def mock_gitlab_api_cls() -> Generator[MagicMock]:
    with patch("qontract_api.gitlab.gitlab_client_factory.GitlabApi") as mock_cls:
        yield mock_cls


def test_factory_resolves_secret(
    mock_gitlab_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    create_gitlab_workspace_client(
        secret=_SECRET,
        url="https://gitlab.example.com",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    mock_secret_manager.read.assert_called_once_with(_SECRET)


def test_factory_returns_workspace_client(
    mock_gitlab_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    client = create_gitlab_workspace_client(
        secret=_SECRET,
        url="https://gitlab.example.com",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    assert isinstance(client, GitlabWorkspaceClient)
    assert client.cache is mock_cache
    assert client.settings is mock_settings


def test_factory_wires_expected_client_kwargs(
    mock_gitlab_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.read.return_value = "test-token"

    create_gitlab_workspace_client(
        secret=_SECRET,
        url="https://gitlab.example.com",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
        ssl_verify=False,
    )

    mock_gitlab_api_cls.assert_called_once_with(
        url="https://gitlab.example.com",
        token="test-token",
        ssl_verify=False,
        timeout=mock_settings.gitlab_projects.api_timeout,
    )


def test_factory_cache_key_uses_url(
    mock_gitlab_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    client = create_gitlab_workspace_client(
        secret=_SECRET,
        url="https://gitlab.other.com",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    assert "gitlab.other.com" in client._cache_key_group("team")


def test_factory_stores_resolved_token(
    mock_gitlab_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_secret_manager.read.return_value = "test-token"

    client = create_gitlab_workspace_client(
        secret=_SECRET,
        url="https://gitlab.example.com",
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=mock_settings,
    )

    assert client._token == "test-token"
