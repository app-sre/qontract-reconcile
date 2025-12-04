"""Factory for creating PagerDutyWorkspaceClient instances with rate limiting.

Service layer should use PagerDutyWorkspaceClient, not PagerDutyApi directly.
"""

from qontract_utils.pagerduty_api import PagerDutyApi, PagerDutyApiCallContext
from qontract_utils.secret_reader import SecretBackend

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.pagerduty.pagerduty_workspace_client import (
    PagerDutyWorkspaceClient,
)
from qontract_api.logger import get_logger
from qontract_api.rate_limit.token_bucket import TokenBucket

logger = get_logger(__name__)


def create_pagerduty_api(
    instance_name: str,
    token: str,
    cache: CacheBackend,
    settings: Settings,
) -> PagerDutyApi:
    """Create PagerDutyApi instance with rate limiting hook and config from settings.

    Creates a TokenBucket rate limiter configured from settings and injects it
    as a before_api_call_hook into PagerDutyApi. This ensures all PagerDuty API calls
    are rate-limited according to the configured tier.

    Prometheus metrics are automatically tracked via the built-in _metrics_hook.

    Args:
        instance_name: PagerDuty instance name
        token: PagerDuty API token
        cache: Cache backend for distributed rate limit state
        settings: Application settings with PagerDuty configuration

    Returns:
        PagerDutyApi instance with rate limiting hook and config from settings
    """
    # Create token bucket with settings from config
    bucket_name = f"pagerduty:{settings.pagerduty.rate_limit_tier}:{instance_name}"
    token_bucket = TokenBucket(
        cache=cache,
        bucket_name=bucket_name,
        capacity=settings.pagerduty.rate_limit_tokens,
        refill_rate=settings.pagerduty.rate_limit_refill_rate,
    )

    # Create hook function that acquires 1 token before each API call
    def rate_limit_hook(_context: PagerDutyApiCallContext) -> None:
        """Rate limiting hook - acquires token before PagerDuty API call.

        Args:
            _context: API call context with method, verb, and instance info (unused)
        """
        token_bucket.acquire(tokens=1, timeout=30)

    # Create PagerDutyApi with rate limiting hook and config from settings
    return PagerDutyApi(
        instance_name,
        token,
        timeout=settings.pagerduty.api_timeout,
        before_api_call_hooks=[rate_limit_hook],
    )


def create_pagerduty_workspace_client(
    instance_name: str,
    cache: CacheBackend,
    secret_reader: SecretBackend,
    settings: Settings,
) -> PagerDutyWorkspaceClient:
    """Create PagerDutyWorkspaceClient with caching, distributed locking, and rate limiting.

    Creates a PagerDutyApi instance with rate limiting (via create_pagerduty_api) and wraps it
    in a PagerDutyWorkspaceClient that provides:
    - Caching with TTL for PagerDuty data (schedules, escalation policies)
    - Distributed locking for thread-safe cache updates
    - Cache updates instead of invalidation (O(1) performance)

    Args:
        instance_name: PagerDuty instance name
        cache: Cache backend for distributed cache and rate limit state
        secret_manager: Secret backend for retrieving PagerDuty tokens
        settings: Application settings with PagerDuty configuration

    Returns:
        PagerDutyWorkspaceClient instance with full caching + compute layer
    """
    # Get token from secret backend (Vault or env vars)
    if not settings.pagerduty.instances.get(instance_name):
        raise ValueError(f"PagerDuty instance '{instance_name}' not found in settings")

    # Create underlying PagerDutyApi with rate limiting
    pagerduty_api = create_pagerduty_api(
        instance_name=instance_name,
        token=secret_reader.read(settings.pagerduty.instances[instance_name].token),
        cache=cache,
        settings=settings,
    )

    # Wrap in PagerDutyWorkspaceClient for caching + compute layer
    return PagerDutyWorkspaceClient(
        pagerduty_api=pagerduty_api,
        cache=cache,
        settings=settings,
    )
