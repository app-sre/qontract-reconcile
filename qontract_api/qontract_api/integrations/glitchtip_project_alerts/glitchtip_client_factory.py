"""Factory for creating GlitchtipWorkspaceClient instances."""

from qontract_utils.glitchtip_api import GlitchtipApi

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.glitchtip_project_alerts.glitchtip_workspace_client import (
    GlitchtipWorkspaceClient,
)


class GlitchtipClientFactory:
    """Factory for creating GlitchtipWorkspaceClient instances.

    Encapsulates all dependencies and configuration needed to create
    GlitchtipWorkspaceClient instances with caching.
    """

    def __init__(self, cache: CacheBackend, settings: Settings) -> None:
        """Initialize factory with dependencies.

        Args:
            cache: Cache backend for distributed locking and caching
            settings: Application settings with Glitchtip configuration
        """
        self.cache = cache
        self.settings = settings

    @staticmethod
    def create_glitchtip_api(
        host: str,
        token: str,
        read_timeout: int = 30,
        max_retries: int = 3,
    ) -> GlitchtipApi:
        """Create a GlitchtipApi instance.

        Args:
            host: Glitchtip instance host URL
            token: Glitchtip API token
            read_timeout: HTTP read timeout in seconds
            max_retries: Max HTTP retries

        Returns:
            GlitchtipApi instance
        """
        return GlitchtipApi(
            host=host,
            token=token,
            timeout=read_timeout,
            max_retries=max_retries,
        )

    def create_workspace_client(
        self,
        instance_name: str,
        host: str,
        token: str,
        read_timeout: int = 30,
        max_retries: int = 3,
    ) -> GlitchtipWorkspaceClient:
        """Create GlitchtipWorkspaceClient with full stack.

        Creates a GlitchtipApi instance and wraps it in a GlitchtipWorkspaceClient
        that provides caching and the compute layer.

        Args:
            instance_name: Glitchtip instance name (for cache key namespacing)
            host: Glitchtip instance host URL
            token: Glitchtip API token
            read_timeout: HTTP read timeout in seconds
            max_retries: Max HTTP retries

        Returns:
            GlitchtipWorkspaceClient instance with full caching + compute layer
        """
        glitchtip_api = self.create_glitchtip_api(
            host=host,
            token=token,
            read_timeout=read_timeout,
            max_retries=max_retries,
        )

        return GlitchtipWorkspaceClient(
            glitchtip_api=glitchtip_api,
            instance_name=instance_name,
            cache=self.cache,
            settings=self.settings,
        )
