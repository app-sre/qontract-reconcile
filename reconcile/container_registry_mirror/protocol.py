from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from reconcile.container_registry_mirror.mirror_spec import MirrorSpec


class ContainerRegistryMirror(Protocol):
    """Defines the contract that each mirror implementation must satisfy.
    Any class implementing these four methods satisfies the protocol
    without declaring inheritance, equivalent to a Go interface."""

    def resolve_source_credentials(
        self,
        secret_ref: dict[str, Any] | None,
    ) -> str | None:
        """Fetch read credentials for the source registry and return
        them in skopeo's "user:password" format. Returns None for
        public sources requiring no authentication. Handles any
        encoding specific to the credential storage (e.g., base64
        for GCP service account keys)."""
        ...

    def resolve_destination_credentials(self, key: str) -> str:
        """Fetch write credentials for the destination registry and
        return them in skopeo's "user:password" format. The key
        identifies which destination (e.g., an OrgKey for Quay, a
        project name for GCP). Any storage-specific encoding has
        been resolved to plain text by the time this returns."""
        ...

    def should_skip_mirror(
        self,
        source_registry: str,
        source_url: str,
        destination_url: str,
        destination_public: bool | None,
    ) -> bool:
        """Determine whether a specific mirror should be skipped.
        The Quay implementation blocks docker.io sources from being
        mirrored to public repos (security: authenticated mirror
        credentials could re-expose images to the public internet).
        Implementations with no skip conditions return False."""
        ...

    def discover_mirrors(self) -> list[MirrorSpec]:
        """Query app-interface (or another data source) to determine
        what should be mirrored and to where. Each implementation
        knows its own GraphQL queries and schema structure. Returns
        MirrorSpec instances with credentials already resolved."""
        ...
