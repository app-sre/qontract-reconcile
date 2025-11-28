"""Factory for creating SlackWorkspaceClient instances with rate limiting.

Service layer should use SlackWorkspaceClient, not SlackApi directly.
"""

from qontract_utils.slack_api import SlackApi, SlackApiCallContext

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.integrations.slack_usergroups.slack_workspace_client import (
    SlackWorkspaceClient,
)
from qontract_api.rate_limit.token_bucket import TokenBucket


def create_slack_api(
    workspace_name: str,
    token: str,
    cache: CacheBackend,
    settings: Settings,
) -> SlackApi:
    """Create SlackApi instance with rate limiting hook and config from settings.

    Creates a TokenBucket rate limiter configured from settings and injects it
    as a before_api_call_hook into SlackApi. This ensures all Slack API calls
    are rate-limited according to the configured tier.

    Prometheus metrics are automatically tracked via the built-in _metrics_hook.

    Args:
        workspace_name: Slack workspace name
        token: Slack API token
        cache: Cache backend for distributed rate limit state
        settings: Application settings with Slack configuration

    Returns:
        SlackApi instance with rate limiting hook and config from settings
    """
    # Create token bucket with settings from config
    bucket_name = f"slack:{settings.slack.rate_limit_tier}:{workspace_name}"
    token_bucket = TokenBucket(
        cache=cache,
        bucket_name=bucket_name,
        capacity=settings.slack.rate_limit_tokens,
        refill_rate=settings.slack.rate_limit_refill_rate,
    )

    # Create hook function that acquires 1 token before each API call
    def rate_limit_hook(_context: SlackApiCallContext) -> None:
        """Rate limiting hook - acquires token before Slack API call.

        Args:
            _context: API call context with method, verb, and workspace info (unused)
        """
        token_bucket.acquire(tokens=1, timeout=30)

    # Create SlackApi with rate limiting hook and config from settings
    return SlackApi(
        workspace_name,
        token,
        timeout=settings.slack.api_timeout,
        max_retries=settings.slack.api_max_retries,
        method_configs=settings.slack.api_method_configs,
        before_api_call_hooks=[rate_limit_hook],
    )


def create_slack_workspace_client(
    workspace_name: str,
    token: str,
    cache: CacheBackend,
    settings: Settings,
) -> SlackWorkspaceClient:
    """Create SlackWorkspaceClient with caching, distributed locking, and rate limiting.

    Creates a SlackApi instance with rate limiting (via create_slack_api) and wraps it
    in a SlackWorkspaceClient that provides:
    - Caching with TTL for Slack data (users, usergroups, channels)
    - Distributed locking for thread-safe cache updates
    - Cache updates instead of invalidation (O(1) performance)
    - Compute helpers (e.g., get_users_by_ids, get_usergroup_by_handle)

    Args:
        workspace_name: Slack workspace name
        token: Slack API token
        cache: Cache backend for distributed cache and rate limit state
        settings: Application settings with Slack configuration

    Returns:
        SlackWorkspaceClient instance with full caching + compute layer
    """
    # Create underlying SlackApi with rate limiting
    slack_api = create_slack_api(
        workspace_name=workspace_name,
        token=token,
        cache=cache,
        settings=settings,
    )

    # Wrap in SlackWorkspaceClient for caching + compute layer
    return SlackWorkspaceClient(
        slack_api=slack_api,
        cache=cache,
        settings=settings,
    )
