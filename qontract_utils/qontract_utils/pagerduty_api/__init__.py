"""PagerDuty API client and models.

This package provides a stateless PagerDuty API client following the three-layer
architecture pattern (ADR-014).

Layer 1 (Pure Communication):
- PagerDutyApi: Stateless API client with hooks for metrics and rate limiting
- PagerDutyUser: Pydantic model for user data

Hook System (ADR-006):
- PagerDutyApiCallContext: Context passed to hooks
- pre_hooks: Hook system for metrics, rate limiting, logging

Example:
    >>> from qontract_utils.pagerduty_api import PagerDutyApi, PagerDutyUser
    >>> api = PagerDutyApi(instance_name="app-sre", token="...")
    >>> users = api.get_schedule_users(schedule_id="ABC123")
    >>> for user in users:
    ...     print(user.org_username)
"""

from qontract_utils.pagerduty_api.client import (
    TIMEOUT,
    PagerDutyApi,
    PagerDutyApiCallContext,
)
from qontract_utils.pagerduty_api.models import PagerDutyUser

__all__ = [
    "TIMEOUT",
    "PagerDutyApi",
    "PagerDutyApiCallContext",
    "PagerDutyUser",
]
