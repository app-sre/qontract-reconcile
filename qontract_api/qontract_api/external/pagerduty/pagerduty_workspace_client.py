"""PagerDutyWorkspaceClient: Caching + compute layer for PagerDuty instance data.

This layer sits between the stateless PagerDutyApi and business logic, providing:
- Two-tier caching (memory + Redis) for PagerDuty data
- Distributed locking for thread-safe cache updates
- Cache updates instead of invalidation (O(1) performance)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from qontract_utils.pagerduty_api import PagerDutyApi, PagerDutyUser

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = logging.getLogger(__name__)


class CachedScheduleUsers(BaseModel, frozen=True):
    """Cached list of PagerDutyUser objects (for two-tier cache serialization)."""

    items: list[PagerDutyUser] = Field(default_factory=list)


class CachedEscalationPolicyUsers(BaseModel, frozen=True):
    """Cached list of PagerDutyUser objects (for two-tier cache serialization)."""

    items: list[PagerDutyUser] = Field(default_factory=list)


class PagerDutyWorkspaceClient:
    """Caching + compute layer for PagerDuty instance data.

    Provides:
    - Cached access to schedule users and escalation policy users with TTL
    - Distributed locking for thread-safe cache updates
    - Cache updates instead of invalidation for better performance
    """

    def __init__(
        self,
        pagerduty_api: PagerDutyApi,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize PagerDutyWorkspaceClient.

        Args:
            pagerduty_api: Stateless PagerDuty API client
            cache: Cache backend with two-tier caching (memory + Redis)
            settings: Application settings with PagerDuty config
        """
        self.pagerduty_api = pagerduty_api
        self.cache = cache
        self.settings = settings

    # CACHE KEY HELPERS
    def _cache_key_schedule_users(self, schedule_id: str) -> str:
        """Generate cache key for schedule users."""
        return (
            f"pagerduty:{self.pagerduty_api.instance_name}:schedule:{schedule_id}:users"
        )

    def _cache_key_escalation_policy_users(self, policy_id: str) -> str:
        """Generate cache key for escalation policy users."""
        return f"pagerduty:{self.pagerduty_api.instance_name}:escalation_policy:{policy_id}:users"

    # CACHE OPERATIONS (using two-tier cache from CacheBackend)
    def _get_cached_schedule_users(self, cache_key: str) -> list[PagerDutyUser] | None:
        """Get cached schedule users."""
        cached = self.cache.get_obj(cache_key, CachedScheduleUsers)
        return cached.items if cached else None

    def _get_cached_escalation_policy_users(
        self, cache_key: str
    ) -> list[PagerDutyUser] | None:
        """Get cached escalation policy users."""
        cached = self.cache.get_obj(cache_key, CachedEscalationPolicyUsers)
        return cached.items if cached else None

    def _set_cached_schedule_users(
        self, cache_key: str, users: list[PagerDutyUser], ttl: int
    ) -> None:
        """Set cached schedule users."""
        cached = CachedScheduleUsers(items=users)
        self.cache.set_obj(cache_key, cached, ttl)

    def _set_cached_escalation_policy_users(
        self, cache_key: str, users: list[PagerDutyUser], ttl: int
    ) -> None:
        """Set cached escalation policy users."""
        cached = CachedEscalationPolicyUsers(items=users)
        self.cache.set_obj(cache_key, cached, ttl)

    # CACHED DATA ACCESS
    def get_schedule_users(self, schedule_id: str) -> list[PagerDutyUser]:
        """Get users currently on-call in a schedule (cached with distributed locking).

        Args:
            schedule_id: PagerDuty schedule ID

        Returns:
            List of PagerDutyUser objects with org_username
        """
        cache_key = self._cache_key_schedule_users(schedule_id)

        # Try cache first (no lock for reads)
        if cached := self._get_cached_schedule_users(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_schedule_users(cache_key):
                return cached

            # Fetch from API
            users = self.pagerduty_api.get_schedule_users(schedule_id)

            # Cache
            self._set_cached_schedule_users(
                cache_key, users, self.settings.pagerduty.schedule_cache_ttl
            )

            return users

    def get_escalation_policy_users(self, policy_id: str) -> list[PagerDutyUser]:
        """Get users in an escalation policy (cached with distributed locking).

        Args:
            policy_id: PagerDuty escalation policy ID

        Returns:
            List of PagerDutyUser objects with org_username
        """
        cache_key = self._cache_key_escalation_policy_users(policy_id)

        # Try cache first (no lock for reads)
        if cached := self._get_cached_escalation_policy_users(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_escalation_policy_users(cache_key):
                return cached

            # Fetch from API
            users = self.pagerduty_api.get_escalation_policy_users(policy_id)

            # Cache
            self._set_cached_escalation_policy_users(
                cache_key, users, self.settings.pagerduty.escalation_policy_cache_ttl
            )

            return users
