from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from reconcile.gql_definitions.skupper_network.skupper_networks import (
    ClusterPeeringConnectionClusterAccepterV1,
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterV1,
    NamespaceV1,
)


class SkupperCluster(BaseModel):
    name: str


class SkupperSite(BaseModel):
    name: str
    # k8s objects retrieved from app-interface and already rendered
    site_controller_objects: list[dict[str, Any]]
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
                    ClusterPeeringConnectionClusterRequesterV1
                    | ClusterPeeringConnectionClusterAccepterV1,
                )
            ) and c.cluster.name == other.cluster.name:
                return True
        return False

    @property
    def is_edge_site(self) -> bool:
        """Return True if the site is an edge site."""
        for obj in self.site_controller_objects:
            if obj.get("kind", "").lower() == "configmap" and "edge" in obj.get(
                "data", {}
            ):
                return obj["data"]["edge"].lower() == "true"
        return False

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
        return hashlib.sha256(f"{other}-{self}".encode()).hexdigest()

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
