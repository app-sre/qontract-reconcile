"""Domain models for endpoints-discovery desired state.

These models describe what the client sends from App-Interface. They carry
cluster connections, the current managed endpoints, and the namespace set
needed to decide which endpoints are still wanted.
"""

from typing import Any, Protocol

from pydantic import BaseModel, Field

from qontract_api.models import Secret


class RouteLike(Protocol):
    """Structural type for a route as returned by the Kubernetes layer.

    Layer 3 consumes only these attributes, so it never imports the Layer 1
    client module.
    """

    @property
    def name(self) -> str: ...

    @property
    def host(self) -> str: ...

    @property
    def tls(self) -> bool: ...


class DiscoveredRoute(BaseModel, frozen=True):
    """A live OpenShift route, with routes sharing a host and TLS flag merged.

    The route name is the pipe-joined, sorted set of underlying Route names,
    which is also what the endpoint name encodes.
    """

    name: str = Field(..., description="Pipe-joined sorted Route names")
    host: str = Field(..., description="Route host")
    tls: bool = Field(..., description="Whether TLS is configured")

    @property
    def url(self) -> str:
        return f"{self.host}:{443 if self.tls else 80}"


class CurrentEndpoint(BaseModel, frozen=True):
    """An endpoint currently declared in App-Interface."""

    name: str = Field(..., description="Endpoint name")
    url: str | None = Field(default=None, description="Endpoint URL, if set")


class ClusterConnection(BaseModel, frozen=True):
    """Everything needed to connect to one cluster and honour its config."""

    cluster_name: str = Field(..., description="Cluster identifier")
    server_url: str = Field(..., description="Kubernetes API server URL")
    automation_token: Secret | None = Field(
        default=None,
        description=(
            "Vault reference for the automation token (NOT the token itself). "
            "Required only when a namespace on this cluster is discovered; "
            "filtered or disabled namespaces keep their endpoints without a "
            "connection."
        ),
    )
    insecure_skip_tls_verify: bool = Field(
        default=False, description="Skip TLS certificate verification"
    )
    internal: bool | None = Field(
        default=None, description="Whether the cluster is internal"
    )
    disabled_integrations: list[str] = Field(
        default_factory=list,
        description="Integrations disabled for this cluster",
    )


class NamespaceDesiredState(BaseModel, frozen=True):
    """A namespace from App-Interface, with discovery eligibility."""

    name: str = Field(..., description="Namespace name")
    labels: dict[str, str] = Field(
        default_factory=dict, description="Namespace labels used for ignore keys"
    )
    delete: bool = Field(default=False, description="True = namespace is being removed")
    discover: bool = Field(
        default=True,
        description=(
            "False = keep existing endpoints but do not discover routes. "
            "Filtered namespaces stay in the non-deleted set so their "
            "endpoints are never treated as removed."
        ),
    )
    cluster: ClusterConnection = Field(..., description="Cluster connection details")


class DesiredApp(BaseModel, frozen=True):
    """An App-Interface application and its endpoints/namespaces."""

    name: str = Field(..., description="Application name")
    path: str = Field(..., description="Application file path in App-Interface")
    labels: dict[str, str] = Field(
        default_factory=dict, description="Application labels used for ignore keys"
    )
    end_points: list[CurrentEndpoint] = Field(
        default_factory=list, description="Currently declared endpoints"
    )
    namespaces: list[NamespaceDesiredState] = Field(
        default_factory=list, description="Namespaces belonging to the application"
    )


class AppInterfaceRepo(BaseModel, frozen=True):
    """The App-Interface repository the merge request targets."""

    repo_url: str = Field(..., description="Repository URL")
    token: Secret = Field(..., description="Vault reference for the repository token")
    target_branch: str = Field(default="master", description="Merge request target")


class AppEndpointPlan(BaseModel, frozen=True):
    """One endpoint to add, change or delete in an application file."""

    name: str = Field(
        ..., description="Current endpoint name to change or delete; new name for adds"
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Rendered endpoint content from the template (empty for deletes)",
    )
