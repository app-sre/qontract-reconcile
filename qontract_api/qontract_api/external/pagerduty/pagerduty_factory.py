"""Factory for creating PagerDutyWorkspaceClient instances with rate limiting.

Service layer should use PagerDutyWorkspaceClient, not PagerDutyApi directly.
"""

import hashlib

from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, Hooks
from qontract_utils.pagerduty_api import PagerDutyApi
from qontract_utils.secret_reader import Secret

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.pagerduty.pagerduty_workspace_client import (
    PagerDutyWorkspaceClient,
)
from qontract_api.logger import get_logger
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


def create_pagerduty_api(id: str, token: str, timeout: int) -> PagerDutyApi:  # noqa: A002
    """Create PagerDutyApi instance with config from settings.

    Attention: PagerDuty REST Client implementation does have built-in rate limiting.

    Returns:
        PagerDutyApi instance with rate limiting hook and config from settings
    """
    return PagerDutyApi(
        id, token, timeout=timeout, hooks=Hooks(retry_config=DEFAULT_RETRY_CONFIG)
    )


def create_pagerduty_workspace_client(
    secret: Secret,
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
        secret: Secret reference for PagerDuty API token
        cache: Cache backend for distributed cache and rate limit state
        secret_manager: Secret backend for retrieving PagerDuty tokens
        settings: Application settings with PagerDuty configuration

    Returns:
        PagerDutyWorkspaceClient instance with full caching + compute layer
    """
    token = secret_manager.read(secret)
    # Create underlying PagerDutyApi with rate limiting
    pagerduty_api = create_pagerduty_api(
        id=hashlib.pbkdf2_hmac(
            "sha256", token.encode(), settings.jwt_secret_key.encode(), 10000
        ).hex()[:10],
        token=token,
        timeout=settings.pagerduty.api_timeout,
    )

    # Wrap in PagerDutyWorkspaceClient for caching + compute layer
    return PagerDutyWorkspaceClient(
        pagerduty_api=pagerduty_api,
        cache=cache,
        settings=settings,
    )
