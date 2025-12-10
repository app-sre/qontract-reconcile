"""Factory for creating SlackWorkspaceClient instances."""

from qontract_utils.slack_api import SlackApi

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups.slack_workspace_client import (
    SlackWorkspaceClient,
)


class SlackClientFactory:
    """Factory for creating SlackWorkspaceClient instances.

    Encapsulates all dependencies and configuration needed to create
    SlackWorkspaceClient instances with rate limiting and caching.
    """

    def __init__(self, cache: CacheBackend, settings: Settings) -> None:
        """Initialize factory with dependencies.

        Args:
            cache: Cache backend for distributed rate limiting and caching
            settings: Application settings with Slack configuration
        """
        self.cache = cache
        self.settings = settings

    def create_slack_api(self, workspace_name: str, token: str) -> SlackApi:
        """Create SlackApi instance.

        SlackApi does handle direct API calls with rate limiting.

        Args:
            workspace_name: Slack workspace name
            token: Slack API token

        Returns:
            SlackApi instance with rate limiting hook
        """
        # Create SlackApi with config from settings
        return SlackApi(
            slack_api_url=self.settings.slack.api_url,
            workspace_name=workspace_name,
            token=token,
            timeout=self.settings.slack.api_timeout,
            max_retries=self.settings.slack.api_max_retries,
            method_configs=self.settings.slack.api_method_configs,
            pre_hooks=[],
        )

    def create_workspace_client(
        self, workspace_name: str, token: str
    ) -> SlackWorkspaceClient:
        """Create SlackWorkspaceClient with full stack.

        Creates a SlackApi instance and wraps it in a SlackWorkspaceClient that
        provides caching and compute layer.

        Args:
            workspace_name: Slack workspace name
            token: Slack API token

        Returns:
            SlackWorkspaceClient instance with full caching + compute layer
        """
        slack_api = self.create_slack_api(workspace_name=workspace_name, token=token)

        return SlackWorkspaceClient(
            slack_api=slack_api,
            cache=self.cache,
            settings=self.settings,
        )
