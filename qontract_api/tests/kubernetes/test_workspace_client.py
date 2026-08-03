"""Tests for Kubernetes workspace client module."""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from qontract_api.kubernetes.workspace_client import (
    CachedNamespaceNames,
    KubernetesWorkspaceClient,
)

if TYPE_CHECKING:
    from qontract_api.config import Settings


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


def _mock_namespace(name: str) -> MagicMock:
    ns = MagicMock()
    ns.metadata.name = name
    return ns


def test_namespace_exists_cache_hit(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Cache hit returns True when name is in cached set."""
    mock_cache.get_obj.return_value = CachedNamespaceNames(
        names=frozenset({"my-ns", "other-ns"})
    )
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("my-ns") is True
    mock_kubernetes_api.list_namespaces.assert_not_called()


def test_namespace_exists_cache_hit_false(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Cache hit returns False when name is not in cached set."""
    mock_cache.get_obj.return_value = CachedNamespaceNames(
        names=frozenset({"other-ns"})
    )
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("missing-ns") is False
    mock_kubernetes_api.list_namespaces.assert_not_called()


def test_namespace_exists_cache_miss(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Cache miss lists all namespaces, caches the set, checks membership."""
    mock_cache.get_obj.return_value = None
    mock_kubernetes_api.list_namespaces.return_value = [
        _mock_namespace("ns-a"),
        _mock_namespace("ns-b"),
    ]
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("ns-a") is True
    mock_kubernetes_api.list_namespaces.assert_called_once()
    mock_cache.set_obj.assert_called_once()
    cached_value = mock_cache.set_obj.call_args[0][1]
    assert isinstance(cached_value, CachedNamespaceNames)
    assert cached_value.names == frozenset({"ns-a", "ns-b"})


def test_namespace_exists_double_check_locking(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """After acquiring lock, checks cache again before listing."""
    mock_cache.get_obj.side_effect = [
        None,
        CachedNamespaceNames(names=frozenset({"my-ns"})),
    ]
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("my-ns") is True
    mock_kubernetes_api.list_namespaces.assert_not_called()
    mock_cache.lock.assert_called_once()


def test_namespace_exists_sets_correct_ttl(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Cache set uses TTL from settings."""
    mock_cache.get_obj.return_value = None
    mock_kubernetes_api.list_namespaces.return_value = [_mock_namespace("ns")]
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    client.namespace_exists("ns")
    ttl_arg = mock_cache.set_obj.call_args[0][2]
    assert ttl_arg == mock_settings.kubernetes.namespace_cache_ttl


def test_namespace_exists_single_list_for_multiple_checks(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """Multiple exists checks reuse the same cached set (one API call)."""
    cached = CachedNamespaceNames(names=frozenset({"ns-a", "ns-b", "ns-c"}))
    mock_cache.get_obj.side_effect = [
        None,
        None,
        cached,
        cached,
        cached,
    ]
    mock_kubernetes_api.list_namespaces.return_value = [
        _mock_namespace("ns-a"),
        _mock_namespace("ns-b"),
        _mock_namespace("ns-c"),
    ]
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)

    assert client.namespace_exists("ns-a") is True
    assert client.namespace_exists("ns-b") is True
    assert client.namespace_exists("ns-c") is True
    mock_kubernetes_api.list_namespaces.assert_called_once()


def test_create_namespace_delegates_and_invalidates(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """create_namespace delegates to Layer 1 and invalidates cache."""
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)
    client.create_namespace("new-ns")

    mock_kubernetes_api.create_namespace.assert_called_once_with("new-ns")
    mock_cache.delete.assert_called_once_with("kubernetes:test-cluster:namespace_names")


def test_delete_namespace_delegates_and_invalidates(
    mock_kubernetes_api: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    """delete_namespace delegates to Layer 1 and invalidates cache."""
    client = _make_client(mock_kubernetes_api, mock_cache, mock_settings)
    client.delete_namespace("old-ns")

    mock_kubernetes_api.delete_namespace.assert_called_once_with("old-ns")
    mock_cache.delete.assert_called_once_with("kubernetes:test-cluster:namespace_names")


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
