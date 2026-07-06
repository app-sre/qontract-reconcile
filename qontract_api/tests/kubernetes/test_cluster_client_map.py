"""Tests for cluster client map module."""

from unittest.mock import MagicMock, patch

import pytest

from qontract_api.cache.base import CacheBackend
from qontract_api.config import Settings
from qontract_api.kubernetes.cluster_client_map import (
    ClusterClientMap,
    ClusterConnectionParams,
)


@pytest.fixture
def mock_cache() -> MagicMock:
    m = MagicMock(spec=CacheBackend)
    m.get_obj.return_value = None
    m.lock.return_value.__enter__ = MagicMock()
    m.lock.return_value.__exit__ = MagicMock(return_value=False)
    return m


@pytest.fixture
def mock_settings() -> Settings:
    return Settings()


@pytest.fixture
def two_clusters() -> list[ClusterConnectionParams]:
    return [
        ClusterConnectionParams(
            cluster_name="prod-1",
            server="https://prod-1:6443",
            token="token-1",
        ),
        ClusterConnectionParams(
            cluster_name="prod-2",
            server="https://prod-2:6443",
            token="token-2",
        ),
    ]


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_get_returns_workspace_client(
    mock_api_cls: MagicMock,
    two_clusters: list[ClusterConnectionParams],
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    from qontract_api.kubernetes.workspace_client import KubernetesWorkspaceClient

    cluster_map = ClusterClientMap(two_clusters, mock_cache, mock_settings)
    client = cluster_map.get("prod-1")
    assert isinstance(client, KubernetesWorkspaceClient)


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_get_different_clusters_return_different_clients(
    mock_api_cls: MagicMock,
    two_clusters: list[ClusterConnectionParams],
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    cluster_map = ClusterClientMap(two_clusters, mock_cache, mock_settings)
    c1 = cluster_map.get("prod-1")
    c2 = cluster_map.get("prod-2")
    assert c1 is not c2


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_get_unknown_cluster_raises_key_error(
    mock_api_cls: MagicMock,
    two_clusters: list[ClusterConnectionParams],
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    cluster_map = ClusterClientMap(two_clusters, mock_cache, mock_settings)
    with pytest.raises(KeyError, match="unknown"):
        cluster_map.get("unknown")


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_iter_yields_cluster_names(
    mock_api_cls: MagicMock,
    two_clusters: list[ClusterConnectionParams],
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    cluster_map = ClusterClientMap(two_clusters, mock_cache, mock_settings)
    assert sorted(cluster_map) == ["prod-1", "prod-2"]


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_items_yields_name_client_pairs(
    mock_api_cls: MagicMock,
    two_clusters: list[ClusterConnectionParams],
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    from qontract_api.kubernetes.workspace_client import KubernetesWorkspaceClient

    cluster_map = ClusterClientMap(two_clusters, mock_cache, mock_settings)
    items = dict(cluster_map.items())
    assert "prod-1" in items
    assert "prod-2" in items
    assert all(isinstance(v, KubernetesWorkspaceClient) for v in items.values())


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_cleanup_closes_all_api_clients(
    mock_api_cls: MagicMock,
    two_clusters: list[ClusterConnectionParams],
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    cluster_map = ClusterClientMap(two_clusters, mock_cache, mock_settings)
    cluster_map.cleanup()
    assert mock_api_cls.return_value.close.call_count == 2


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_context_manager_calls_cleanup(
    mock_api_cls: MagicMock,
    two_clusters: list[ClusterConnectionParams],
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    with ClusterClientMap(two_clusters, mock_cache, mock_settings):
        pass
    mock_api_cls.return_value.close.assert_called()


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_connection_failure_raises_immediately(
    mock_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    mock_api_cls.side_effect = Exception("connection refused")
    params = [
        ClusterConnectionParams(
            cluster_name="bad", server="https://bad:6443", token="tok"
        ),
    ]
    with pytest.raises(Exception, match="connection refused"):
        ClusterClientMap(params, mock_cache, mock_settings)


@patch(
    "qontract_api.kubernetes.cluster_client_map.KubernetesApi",
    autospec=True,
)
def test_empty_clusters(
    mock_api_cls: MagicMock,
    mock_cache: MagicMock,
    mock_settings: Settings,
) -> None:
    cluster_map = ClusterClientMap([], mock_cache, mock_settings)
    assert list(cluster_map) == []
