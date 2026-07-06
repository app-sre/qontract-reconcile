"""Domain models for openshift-namespaces desired state."""

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class DesiredNamespace(BaseModel, frozen=True):
    """A namespace that should exist or be deleted on a cluster."""

    name: str = Field(..., description="Namespace name")
    delete: bool = Field(
        default=False, description="True = namespace should be removed"
    )


class ClusterNamespaces(BaseModel, frozen=True):
    """Cluster with its desired namespaces and connection info."""

    cluster_name: str = Field(..., description="Cluster identifier")
    server_url: str = Field(..., description="Kubernetes API server URL")
    automation_token: Secret = Field(
        ...,
        description="Vault reference for the automation token (NOT the actual token)",
    )
    insecure_skip_tls_verify: bool = Field(
        default=False, description="Skip TLS certificate verification"
    )
    namespaces: list[DesiredNamespace] = Field(
        default_factory=list, description="Desired namespaces for this cluster"
    )
