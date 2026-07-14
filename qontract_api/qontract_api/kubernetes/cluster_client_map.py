"""Multi-cluster workspace client map.

DRY helper for integrations that operate across multiple Kubernetes clusters.
Maps cluster names to KubernetesWorkspaceClient instances.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import BaseModel
from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, Hooks
from qontract_utils.kubernetes import KubernetesApi

from qontract_api.kubernetes.workspace_client import KubernetesWorkspaceClient
from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import ItemsView, Iterable, Iterator

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class ClusterConnectionParams(BaseModel, frozen=True):
    """Typed connection parameters for a Kubernetes cluster."""

    cluster_name: str
    server: str
    token: str
    insecure_skip_tls_verify: bool = False


class ClusterClientMap:
    """Maps cluster names to KubernetesWorkspaceClient instances.

    Creates a Layer 1 KubernetesApi and Layer 2 KubernetesWorkspaceClient
    for each cluster. Fails loud on connection errors — no silent error
    sentinels.
    """

    def __init__(
        self,
        clusters: Iterable[ClusterConnectionParams],
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        self._clients: dict[str, KubernetesWorkspaceClient] = {}
        self._api_clients: list[KubernetesApi] = []

        try:
            for params in clusters:
                api = KubernetesApi(
                    params.server,
                    params.token,
                    insecure_skip_tls_verify=params.insecure_skip_tls_verify,
                    hooks=Hooks(retry_config=DEFAULT_RETRY_CONFIG),
                )
                self._api_clients.append(api)
                self._clients[params.cluster_name] = KubernetesWorkspaceClient(
                    kubernetes_api=api,
                    cluster_name=params.cluster_name,
                    cache=cache,
                    settings=settings,
                )
        except Exception:
            self.cleanup()
            raise

    def get(self, cluster_name: str) -> KubernetesWorkspaceClient:
        """Get workspace client for a cluster.

        Raises:
            KeyError: If cluster_name is unknown.
        """
        if cluster_name not in self._clients:
            msg = f"Unknown cluster {cluster_name!r}"
            raise KeyError(msg)
        return self._clients[cluster_name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._clients)

    def items(self) -> ItemsView[str, KubernetesWorkspaceClient]:
        """Return (cluster_name, workspace_client) pairs."""
        return self._clients.items()

    def cleanup(self) -> None:
        """Close all underlying API clients."""
        for api in self._api_clients:
            try:
                api.close()
            except Exception:
                logger.exception("Failed to close Kubernetes API client")
        self._api_clients.clear()
        self._clients.clear()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.cleanup()
