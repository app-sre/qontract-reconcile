"""Factory for creating SlackWorkspaceClient instances.

Encapsulates the creation of SlackWorkspaceClient with all dependencies:
- Rate limiting via TokenBucket
- Caching and distributed locking
- Configuration from settings

Following the same pattern as CacheBackend factory pattern.
"""

from qontract_utils.slack_api import SlackApi, SlackApiCallContext

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups.slack_workspace_client import (
    SlackWorkspaceClient,
)
from qontract_api.rate_limit.token_bucket import TokenBucket


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
        """Create SlackApi instance with rate limiting.

        Creates a TokenBucket rate limiter and injects it as a hook into SlackApi.

        Args:
            workspace_name: Slack workspace name
            token: Slack API token

        Returns:
            SlackApi instance with rate limiting hook
        """
        # Create token bucket with settings from config
        bucket_name = f"slack:{self.settings.slack.rate_limit_tier}:{workspace_name}"
        token_bucket = TokenBucket(
            cache=self.cache,
            bucket_name=bucket_name,
            capacity=self.settings.slack.rate_limit_tokens,
            refill_rate=self.settings.slack.rate_limit_refill_rate,
        )

        # Create hook function that acquires 1 token before each API call
        def rate_limit_hook(_context: SlackApiCallContext) -> None:
            """Rate limiting hook - acquires token before Slack API call."""
            token_bucket.acquire(tokens=1, timeout=30)

        # Create SlackApi with rate limiting hook and config from settings
        return SlackApi(
            slack_api_url=self.settings.slack.api_url,
            workspace_name=workspace_name,
            token=token,
            timeout=self.settings.slack.api_timeout,
            max_retries=self.settings.slack.api_max_retries,
            method_configs=self.settings.slack.api_method_configs,
            before_api_call_hooks=[rate_limit_hook],
        )

    def create_workspace_client(
        self, workspace_name: str, token: str
    ) -> SlackWorkspaceClient:
        """Create SlackWorkspaceClient with full stack.

        Creates a SlackApi instance with rate limiting and wraps it
        in a SlackWorkspaceClient that provides caching and compute layer.

        Args:
            workspace_name: Slack workspace name
            token: Slack API token

        Returns:
            SlackWorkspaceClient instance with full caching + compute layer
        """
        # Create underlying SlackApi with rate limiting
        slack_api = self.create_slack_api(
            workspace_name=workspace_name,
            token=token,
        )

        # Wrap in SlackWorkspaceClient for caching + compute layer
        return SlackWorkspaceClient(
            slack_api=slack_api,
            cache=self.cache,
            settings=self.settings,
        )
