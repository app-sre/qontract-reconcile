"""Tests for openshift-namespaces tasks."""

from unittest.mock import MagicMock

from qontract_api.integrations.openshift_namespaces.domain import (
    ClusterNamespaces,
    DesiredNamespace,
)
from qontract_api.integrations.openshift_namespaces.tasks import generate_lock_key
from qontract_api.models import Secret


def _secret() -> Secret:
    return Secret(
        secret_manager_url="https://vault", path="k8s/prod/token", field="token"
    )


def _cluster(name: str = "prod-1") -> ClusterNamespaces:
    return ClusterNamespaces(
        cluster_name=name,
        server_url=f"https://{name}:6443",
        automation_token=_secret(),
        namespaces=[DesiredNamespace(name="app-a")],
    )


def test_generate_lock_key_sorted() -> None:
    """Lock key is sorted cluster names."""
    clusters = [_cluster("z-cluster"), _cluster("a-cluster")]
    key = generate_lock_key(MagicMock(), clusters)
    assert key == "a-cluster,z-cluster"


def test_generate_lock_key_single() -> None:
    key = generate_lock_key(MagicMock(), [_cluster("prod-1")])
    assert key == "prod-1"


def test_generate_lock_key_empty() -> None:
    key = generate_lock_key(MagicMock(), [])
    assert key == ""
