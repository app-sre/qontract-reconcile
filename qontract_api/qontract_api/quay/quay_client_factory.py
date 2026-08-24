"""Factory for creating QuayWorkspaceClient instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.quay_api import QuayApi

from qontract_api.quay.quay_workspace_client import QuayWorkspaceClient

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings


class QuayClientFactory:
    """Factory for creating QuayWorkspaceClient instances.

    Encapsulates dependencies needed to create workspace clients with caching.
    """

    def __init__(self, cache: CacheBackend, settings: Settings) -> None:
        self.cache = cache
        self.settings = settings

    @staticmethod
    def create_quay_api(
        token: str,
        organization: str,
        base_url: str = "quay.io",
    ) -> QuayApi:
        """Create a Layer 1 QuayApi instance."""
        return QuayApi(
            token=token,
            organization=organization,
            base_url=base_url,
        )

    def create_workspace_client(
        self,
        instance_name: str,
        organization: str,
        token: str,
        base_url: str = "quay.io",
    ) -> QuayWorkspaceClient:
        """Create a QuayWorkspaceClient with caching for one org."""
        api = self.create_quay_api(
            token=token,
            organization=organization,
            base_url=base_url,
        )
        return QuayWorkspaceClient(
            quay_api=api,
            instance_name=instance_name,
            organization=organization,
            cache=self.cache,
            settings=self.settings,
        )
