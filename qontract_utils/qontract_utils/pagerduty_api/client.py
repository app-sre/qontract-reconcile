"""PagerDuty API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
rate limiting via hooks (ADR-006).
"""

import contextvars
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from pagerduty import RestApiV2Client
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import DEFAULT_RETRY_CONFIG, RetryConfig, invoke_with_hooks
from qontract_utils.pagerduty_api.models import PagerDutyUser

logger = structlog.get_logger(__name__)

# Prometheus metrics
pagerduty_request = Counter(
    # Following naming convention (qontract_reconcile_external_api_<component>_requests_total) to
    # automatically include this metric in dashboards
    "qontract_reconcile_external_api_pagerduty_requests_total",
    "Total number of PagerDuty API requests",
    ["method", "verb"],
)

pagerduty_request_duration = Histogram(
    "qontract_reconcile_external_api_pagerduty_request_duration_seconds",
    "PagerDuty API request duration in seconds",
    ["method", "verb"],
)

# Local storage for latency tracking
_latency_tracker = contextvars.ContextVar("latency_tracker", default=0.0)

TIMEOUT = 30
TIME_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class PagerDutyApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "schedules.get")
        verb: HTTP verb (e.g., "GET")
        instance: PagerDuty instance name
    """

    method: str
    verb: str
    id: str


def _metrics_hook(context: PagerDutyApiCallContext) -> None:
    """Built-in Prometheus metrics hook.

    Records all API calls with method and verb labels.
    """
    pagerduty_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: PagerDutyApiCallContext) -> None:
    """Built-in hook to start latency measurement.

    Stores the start time in local storage.
    """
    _latency_tracker.set(time.perf_counter())


def _latency_end_hook(context: PagerDutyApiCallContext) -> None:
    """Built-in hook to record latency measurement.

    Calculates duration from start time and records to Prometheus histogram.
    """
    duration = time.perf_counter() - _latency_tracker.get()
    pagerduty_request_duration.labels(context.method, context.verb).observe(duration)
    _latency_tracker.set(0.0)


def _request_log_hook(context: PagerDutyApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("API request", method=context.method, verb=context.verb, id=context.id)


class PagerDutyApi:
    """Stateless PagerDuty API client with hook system.

    Layer 1 (Pure Communication) client following ADR-014. Provides methods
    to fetch users from PagerDuty schedules and escalation policies.

    Hook System (ADR-006):
    - Always includes metrics hook for Prometheus
    - Supports additional hooks via pre_hooks parameter
    - Hooks receive PagerDutyApiCallContext with method, verb, instance

    Example:
        >>> def rate_limit_hook(ctx: PagerDutyApiCallContext) -> None:
        ...     # Rate limiting logic
        ...     pass
        >>> api = PagerDutyApi(
        ...     id="app-sre",
        ...     token="...",
        ...     pre_hooks=[rate_limit_hook]
        ... )
        >>> users = api.get_schedule_users("ABC123")
        >>> for user in users:
        ...     print(user.org_username)
    """

    def __init__(
        self,
        id: str,  # noqa: A002
        token: str,
        timeout: int = TIMEOUT,
        pre_hooks: Iterable[Callable[[PagerDutyApiCallContext], None]] | None = None,
        post_hooks: Iterable[Callable[[PagerDutyApiCallContext], None]] | None = None,
        error_hooks: Iterable[Callable[[PagerDutyApiCallContext], None]] | None = None,
        retry_hooks: Iterable[Callable[[PagerDutyApiCallContext, int], None]]
        | None = None,
        retry_config: RetryConfig | None = DEFAULT_RETRY_CONFIG,
    ) -> None:
        """Initialize PagerDuty API client.

        Args:
            id: PagerDuty ID (for logging, metrics and cache keys)
            token: PagerDuty API token
            timeout: API request timeout in seconds (default: 30)
            pre_hooks: Optional hooks called before API requests
        """
        self.id = id
        self._timeout = timeout

        # Setup hook system - always include built-in hooks
        self._pre_hooks: list[Callable[[PagerDutyApiCallContext], None]] = [
            _metrics_hook,
            _request_log_hook,
            _latency_start_hook,
        ]
        if pre_hooks:
            self._pre_hooks.extend(pre_hooks)
        self._post_hooks: list[Callable[[PagerDutyApiCallContext], None]] = [
            _latency_end_hook
        ]
        if post_hooks:
            self._post_hooks.extend(post_hooks)
        self._error_hooks: list[Callable[[PagerDutyApiCallContext], None]] = []
        if error_hooks:
            self._error_hooks.extend(error_hooks)
        self._retry_hooks: list[Callable[[PagerDutyApiCallContext, int], None]] = []
        if retry_hooks:
            self._retry_hooks.extend(retry_hooks)
        self._retry_config = retry_config

        # Initialize PagerDuty client
        self._client = RestApiV2Client(api_key=token)

    @invoke_with_hooks(
        lambda self: PagerDutyApiCallContext(method="users.get", verb="GET", id=self.id)
    )
    def get_user(self, user_id: str) -> PagerDutyUser:
        """Get PagerDuty user by ID.

        Args:
            user_id: PagerDuty user ID

        Returns:
            PagerDutyUser object with org_username extracted from email

        Example:
            >>> api = PagerDutyApi(instance_name="app-sre", token="...")
            >>> user = api.get_user("P12345")
            >>> print(user.org_username)
            jsmith
        """
        user_data = self._client.rget(f"/users/{user_id}")  # type: ignore[misc]
        return PagerDutyUser(
            id=user_id,
            email=user_data["email"],
            name=user_data["name"],
        )

    @invoke_with_hooks(
        lambda self: PagerDutyApiCallContext(
            method="schedules.get", verb="GET", id=self.id
        )
    )
    def get_schedule_users(self, schedule_id: str) -> list[PagerDutyUser]:
        """Get users currently on-call in a schedule.

        Uses a time window from now to now + 60 seconds to fetch on-call users.
        Extracts organization username from user email addresses.

        Args:
            schedule_id: PagerDuty schedule ID

        Returns:
            List of PagerDutyUser objects with org_username

        Example:
            >>> api = PagerDutyApi(instance_name="app-sre", token="...")
            >>> users = api.get_schedule_users("ABC123")
            >>> print([u.org_username for u in users])
            ['jsmith', 'mdoe']
        """
        # Calculate time window: now to now + 60s
        now = datetime.now(UTC)
        until = now + timedelta(seconds=TIME_WINDOW_SECONDS)

        # Fetch schedule with on-call users in time window
        schedule = self._client.rget(  # type: ignore[misc]
            f"/schedules/{schedule_id}",
            params={
                "since": now.isoformat(),
                "until": until.isoformat(),
                "timezone_zone": "UTC",
            },
        )

        return [
            self.get_user(entry["user"]["id"])
            for entry in schedule["final_schedule"]["rendered_schedule_entries"]
            if not entry["user"].get("deleted_at")
        ]

    @invoke_with_hooks(
        lambda self: PagerDutyApiCallContext(
            method="escalation_policies.get", verb="GET", id=self.id
        )
    )
    def get_escalation_policy_users(self, policy_id: str) -> list[PagerDutyUser]:
        """Get users in an escalation policy.

        Fetches all users across all escalation rules in the policy.
        Extracts organization username from user email addresses.

        Args:
            policy_id: PagerDuty escalation policy ID

        Returns:
            List of PagerDutyUser objects with org_username

        Example:
            >>> api = PagerDutyApi(instance_name="app-sre", token="...")
            >>> users = api.get_escalation_policy_users("XYZ789")
            >>> print([u.org_username for u in users])
            ['jsmith', 'mdoe', 'asmith']
        """
        # Calculate time window: now to now + 60s
        now = datetime.now(UTC)
        until = now + timedelta(seconds=TIME_WINDOW_SECONDS)

        # Fetch escalation policy
        policy = self._client.rget(
            f"/escalation_policies/{policy_id}",
            params={
                "since": now.isoformat(),
                "until": until.isoformat(),
                "timezone_zone": "UTC",
            },
        )  # type: ignore[misc]

        users = []
        for rule in policy["escalation_rules"]:
            for target in rule["targets"]:
                match target["type"]:
                    case "schedule_reference":
                        users.extend(self.get_schedule_users(target["id"]))
                    case "user_reference":
                        users.append(self.get_user(target["id"]))
            if users and rule["escalation_delay_in_minutes"] != 0:
                # process rules until users are found and next escalation is not 0 minutes from now
                break
        return users
