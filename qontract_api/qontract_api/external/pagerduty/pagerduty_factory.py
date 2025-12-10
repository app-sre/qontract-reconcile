"""Factory for creating PagerDutyWorkspaceClient instances with rate limiting.

Service layer should use PagerDutyWorkspaceClient, not PagerDutyApi directly.
"""

from qontract_utils.pagerduty_api import PagerDutyApi

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.pagerduty.pagerduty_workspace_client import (
    PagerDutyWorkspaceClient,
)
from qontract_api.logger import get_logger
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


def create_pagerduty_api(
    instance_name: str, token: str, settings: Settings
) -> PagerDutyApi:
    """Create PagerDutyApi instance with config from settings.

    Attention: PagerDuty REST Client implementation does have built-in rate limiting.

    Returns:
        PagerDutyApi instance with rate limiting hook and config from settings
    """
    return PagerDutyApi(
        instance_name,
        token,
        timeout=settings.pagerduty.api_timeout,
    )


def create_pagerduty_workspace_client(
    instance_name: str,
    cache: CacheBackend,
    secret_manager: SecretManager,
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
        token=secret_manager.read(settings.pagerduty.instances[instance_name].token),
        settings=settings,
    )

    # Wrap in PagerDutyWorkspaceClient for caching + compute layer
    return PagerDutyWorkspaceClient(
        pagerduty_api=pagerduty_api,
        cache=cache,
        settings=settings,
    )
