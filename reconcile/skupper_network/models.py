from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import (
    Any,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)

from reconcile.gql_definitions.skupper_network.skupper_networks import (
    ClusterPeeringConnectionClusterAccepterV1,
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterV1,
    NamespaceV1,
    SkupperSiteConfigDefaultsV1,
    SkupperSiteConfigV1,
)


class Defaults:
    """Define default values for a SkupperSite model."""

    DEFAULT_CLUSTER_LOCAL = False
    DEFAULT_CONSOLE = True
    DEFAULT_CONSOLE_AUTHENTICATION = "openshift"
    DEFAULT_CONSOLE_INGRESS = "route"
    DEFAULT_CONTROLLER_CPU_LIMIT = "500m"
    DEFAULT_CONTROLLER_CPU = "200m"
    DEFAULT_CONTROLLER_MEMORY_LIMIT = "128Mi"
    DEFAULT_CONTROLLER_MEMORY = "128Mi"
    DEFAULT_CONTROLLER_POD_ANTIAFFINITY = "skupper.io/component=controller"
    DEFAULT_CONTROLLER_SERVICE_ANNOTATIONS = "managed-by=qontract-reconcile"
    DEFAULT_EDGE = False
    DEFAULT_INGRESS = "route"
    DEFAULT_ROUTER_CONSOLE = False
    DEFAULT_ROUTER_CPU_LIMIT = "500m"
    DEFAULT_ROUTER_CPU = "200m"
    DEFAULT_ROUTER_LOGGING = "error"
    DEFAULT_ROUTER_MEMORY_LIMIT = "156Mi"
    DEFAULT_ROUTER_MEMORY = "156Mi"
    DEFAULT_ROUTER_POD_ANTIAFFINITY = "skupper.io/component=router"
    DEFAULT_ROUTER_SERVICE_ANNOTATIONS = "managed-by=qontract-reconcile"
    DEFAULT_ROUTERS = 3
    DEFAULT_SERVICE_CONTROLLER = True
    DEFAULT_SERVICE_SYNC = True


class SkupperCluster(BaseModel):
    name: str


class SkupperConfig(BaseModel):
    """Skupper config (skupper-site configmap)."""

    cluster_local: bool = Field(Defaults.DEFAULT_CLUSTER_LOCAL, alias="cluster-local")
    console: bool = Field(Defaults.DEFAULT_CONSOLE, alias="console")
    console_authentication: str = Field(
        Defaults.DEFAULT_CONSOLE_AUTHENTICATION, alias="console-authentication"
    )
    console_ingress: str = Field(
        Defaults.DEFAULT_CONSOLE_INGRESS, alias="console-ingress"
    )
    controller_cpu_limit: str = Field(
        Defaults.DEFAULT_CONTROLLER_CPU_LIMIT, alias="controller-cpu-limit"
    )
    controller_cpu: str = Field(Defaults.DEFAULT_CONTROLLER_CPU, alias="controller-cpu")
    controller_memory_limit: str = Field(
        Defaults.DEFAULT_CONTROLLER_MEMORY_LIMIT, alias="controller-memory-limit"
    )
    controller_memory: str = Field(
        Defaults.DEFAULT_CONTROLLER_MEMORY, alias="controller-memory"
    )
    controller_pod_antiaffinity: str = Field(
        Defaults.DEFAULT_CONTROLLER_POD_ANTIAFFINITY,
        alias="controller-pod-antiaffinity",
    )
    controller_service_annotations: str = Field(
        Defaults.DEFAULT_CONTROLLER_SERVICE_ANNOTATIONS,
        alias="controller-service-annotations",
    )
    edge: bool = Field(Defaults.DEFAULT_EDGE, alias="edge")
    ingress: str = Field(Defaults.DEFAULT_INGRESS, alias="ingress")
    name: str
    router_console: bool = Field(
        Defaults.DEFAULT_ROUTER_CONSOLE, alias="router-console"
    )
    router_cpu_limit: str = Field(
        Defaults.DEFAULT_ROUTER_CPU_LIMIT, alias="router-cpu-limit"
    )
    router_cpu: str = Field(Defaults.DEFAULT_ROUTER_CPU, alias="router-cpu")
    router_memory_limit: str = Field(
        Defaults.DEFAULT_ROUTER_MEMORY_LIMIT, alias="router-memory-limit"
    )
    router_memory: str = Field(Defaults.DEFAULT_ROUTER_MEMORY, alias="router-memory")
    router_logging: str = Field(Defaults.DEFAULT_ROUTER_LOGGING, alias="router-logging")
    router_pod_antiaffinity: str = Field(
        Defaults.DEFAULT_ROUTER_POD_ANTIAFFINITY, alias="router-pod-antiaffinity"
    )
    router_service_annotations: str = Field(
        Defaults.DEFAULT_ROUTER_SERVICE_ANNOTATIONS, alias="router-service-annotations"
    )
    routers: int = Field(Defaults.DEFAULT_ROUTERS, alias="routers")
    service_controller: bool = Field(
        Defaults.DEFAULT_SERVICE_CONTROLLER, alias="service-controller"
    )
    service_sync: bool = Field(Defaults.DEFAULT_SERVICE_SYNC, alias="service-sync")

    class Config:
        allow_population_by_field_name = True

    @classmethod
    def init(
        cls,
        name: str,
        defaults: Optional[SkupperSiteConfigDefaultsV1] = None,
        config: Optional[SkupperSiteConfigV1] = None,
    ) -> SkupperConfig:
        """Create a SkupperConfig instance by merging skupper network defaults, site configs and integration defaults."""
        c: dict[str, Any] = {}

        for field in cls.__fields__:
            if field in ["name"]:
                continue

            c[field] = getattr(Defaults, f"DEFAULT_{field.upper()}")
            if defaults and getattr(defaults, field, None) is not None:
                c[field] = getattr(defaults, field)
            if config and getattr(config, field, None) is not None:
                c[field] = getattr(config, field)

        return cls(name=name, **c)

    def as_configmap_data(self) -> dict[str, str]:
        """Return a dict with the configmap data (keys (field alias) and values as strings)."""
        data = {}
        for k, v in self.dict(by_alias=True).items():
            if isinstance(v, bool):
                # True -> "true", False -> "false"
                v = str(v).lower()
            data[k] = str(v)
        return data


class SkupperSite(BaseModel):
    config: SkupperConfig
    # skupper version
    skupper_site_controller: str
    # integration settings
    connected_sites: set[SkupperSite] = set()
    namespace: NamespaceV1
    delete: bool = False

    def __repr__(self) -> str:
        return f"{self.cluster.name}/{self.namespace.name}"

    def __str__(self) -> str:
        return self.__repr__()

    def __lt__(self, other: SkupperSite) -> bool:
        return self.name < other.name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SkupperSite):
            return False

        return (
            self.name == other.name
            and self.namespace.name == other.namespace.name
            and self.cluster.name == other.cluster.name
        )

    def __hash__(self) -> int:
        return hash(self.name + self.namespace.name + self.cluster.name)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def cluster(self) -> ClusterV1:
        return self.namespace.cluster

    @property
    def on_private_cluster(self) -> bool:
        """Return True if the skupper site is hosted on a private cluster."""
        return self.cluster.spec.private if self.cluster.spec else False

    @property
    def on_public_cluster(self) -> bool:
        """Return True if the skupper site is not hosted on a private cluster."""
        return not self.on_private_cluster

    @property
    def on_internal_cluster(self) -> bool:
        """Return True if the skupper site is hosted on an internal cluster."""
        return self.cluster.internal or False

    def is_peered_with(self, other: SkupperSite) -> bool:
        """Return True if the involved skupper site clusters are peered."""
        if not self.cluster.peering:
            return False

        for c in self.cluster.peering.connections:
            if (
                isinstance(
                    c,
                    (
                        ClusterPeeringConnectionClusterRequesterV1,
                        ClusterPeeringConnectionClusterAccepterV1,
                    ),
                )
            ) and c.cluster.name == other.cluster.name:
                return True
        return False

    @property
    def is_edge_site(self) -> bool:
        """Return True if the site is an edge site."""
        return self.config.edge

    def is_connected_to(self, receiver: SkupperSite) -> bool:
        """Return True if the site has an outgoing connection to the receiver site."""
        return receiver in self.connected_sites

    def has_incoming_connections(self, sites: Iterable[SkupperSite]) -> bool:
        """Return True if the site has at least one incoming connection."""
        return any(other.is_connected_to(self) for other in sites)

    def is_island(self, sites: Iterable[SkupperSite]) -> bool:
        """Return True if the site is not connected to any other skupper site."""
        # Neither incoming nor outgoing connections
        return (
            not self.has_incoming_connections(sites)
            and not self.connected_sites
            and not self.delete
        )

    def compute_connected_sites(self, sites: Iterable[SkupperSite]) -> None:
        """Compute the list of outgoing connections for the site."""
        connected_sites: list[SkupperSite] = []

        # Connect to all other public clusters
        if self.on_public_cluster and not self.delete:
            connected_sites = [
                other
                for other in sites
                if other != self
                and other.on_public_cluster
                and not other.is_edge_site
                and not other.delete
                and not other.is_connected_to(self)
            ]

        # Connect to all public clusters + all other peered & private clusters
        if self.on_private_cluster and not self.delete:
            connected_sites = [
                other
                for other in sites
                if other != self
                and other.on_public_cluster
                and not other.is_edge_site
                and not other.delete
                and not other.is_connected_to(self)
            ]
            connected_sites += [
                other
                for other in sites
                if other != self
                and other.on_private_cluster
                and self.is_peered_with(other)
                and not other.is_edge_site
                and not other.delete
                and not other.is_connected_to(self)
            ]

        # If the site is on an internal cluster, connect to all other internal clusters too
        if self.on_internal_cluster and not self.delete:
            connected_sites += [
                other
                for other in sites
                if other != self
                and other.on_internal_cluster
                and not other.is_edge_site
                and not other.delete
                and not other.is_connected_to(self)
            ]

        self.connected_sites = set(connected_sites)
        logging.debug(f"{self} connected sites: {self.connected_sites}")

    def unique_token_name(self, other: SkupperSite) -> str:
        """Generate a unique token name for a site connection."""
        return hashlib.sha256(f"{other}-{self}".encode("UTF-8")).hexdigest()

    def token_name(self, other: SkupperSite) -> str:
        """Get the token name for a site connection."""
        return other.name

    @property
    def token_labels(self) -> dict[str, str]:
        """Get the token labels."""
        # This label is used to identify the site in the `skupper link status` command
        # self.name ({skupper_network.identifier}-{ns.cluster.name}-{ns.name}) can be longer than 63 characters
        # so use cluster.name-namespaced.name instead and trim it to 63 characters
        # a namespace can't be in more than one skupper network, so it's safe to omit the skupper network identifier
        return {"token-receiver": f"{self.cluster.name}-{self.namespace.name}"[0:63]}
