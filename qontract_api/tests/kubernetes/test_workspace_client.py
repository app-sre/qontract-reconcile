"""Tests for Kubernetes workspace client module."""

from unittest.mock import MagicMock

from qontract_api.config import Settings
from qontract_api.kubernetes.workspace_client import (
    CachedNamespaceExists,
    KubernetesWorkspaceClient,
)


def _make_client(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> KubernetesWorkspaceClient:
    return KubernetesWorkspaceClient(
        kubernetes_api=mock_kubernetes_api,
        cluster_name="test-cluster",
        cache=mock_cache,
        settings=mock_settings,
    )


def test_namespace_exists_cache_hit(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Cache hit returns cached value, no API call."""
    mock_cache.get_obj.return_value = CachedNamespaceExists(exists=True)
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("my-ns") is True
    mock_kubernetes_api.namespace_exists.assert_not_called()


def test_namespace_exists_cache_miss(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Cache miss calls API and stores result."""
    mock_cache.get_obj.return_value = None
    mock_kubernetes_api.namespace_exists.return_value = True
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("my-ns") is True
    mock_kubernetes_api.namespace_exists.assert_called_once_with("my-ns")
    mock_cache.set_obj.assert_called_once()
    cached_value = mock_cache.set_obj.call_args[0][1]
    assert isinstance(cached_value, CachedNamespaceExists)
    assert cached_value.exists is True


def test_namespace_exists_double_check_locking(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """After acquiring lock, checks cache again before calling API."""
    mock_cache.get_obj.side_effect = [
        None,
        CachedNamespaceExists(exists=False),
    ]
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("my-ns") is False
    mock_kubernetes_api.namespace_exists.assert_not_called()
    mock_cache.lock.assert_called_once()


def test_namespace_exists_sets_correct_ttl(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Cache set uses TTL from settings."""
    mock_cache.get_obj.return_value = None
    mock_kubernetes_api.namespace_exists.return_value = True
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    client.namespace_exists("my-ns")
    ttl_arg = mock_cache.set_obj.call_args[0][2]
    assert ttl_arg == mock_settings.kubernetes.namespace_cache_ttl


def test_create_namespace_delegates_and_invalidates(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """create_namespace delegates to Layer 1 and invalidates cache."""
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)
    client.create_namespace("new-ns")

    mock_kubernetes_api.create_namespace.assert_called_once_with("new-ns")
    mock_cache.delete.assert_called_once()


def test_delete_namespace_delegates_and_invalidates(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """delete_namespace delegates to Layer 1 and invalidates cache."""
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)
    client.delete_namespace("old-ns")

    mock_kubernetes_api.delete_namespace.assert_called_once_with("old-ns")
    mock_cache.delete.assert_called_once()


def test_list_namespaces_delegates_no_cache(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """list_namespaces delegates to Layer 1 without caching."""
    mock_kubernetes_api.list_namespaces.return_value = ["ns1", "ns2"]
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    result = client.list_namespaces()
    assert result == ["ns1", "ns2"]
    mock_cache.get_obj.assert_not_called()
    mock_cache.set_obj.assert_not_called()
