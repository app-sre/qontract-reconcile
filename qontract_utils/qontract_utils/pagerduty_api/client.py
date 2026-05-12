"""PagerDuty API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
rate limiting via hooks (ADR-006).
"""

import contextvars
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from pagerduty import RestApiV2Client
from prometheus_client import Counter, Histogram

from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API
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
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)

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

    Pushes the start time onto the stack to support nested calls.
    """
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: PagerDutyApiCallContext) -> None:
    """Built-in hook to record latency measurement.

    Pops the most recent start time from the stack and records duration.
    """
    stack = _latency_tracker.get()
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    pagerduty_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: PagerDutyApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("API request", method=context.method, verb=context.verb, id=context.id)


@with_hooks(
    hooks=Hooks(
        pre_hooks=[
            _metrics_hook,
            _request_log_hook,
            _latency_start_hook,
        ],
        post_hooks=[_latency_end_hook],
    )
)
class PagerDutyApi:
    """Stateless PagerDuty API client with hook system.

    Layer 1 (Pure Communication) client following ADR-014. Provides methods
    to fetch users from PagerDuty schedules and escalation policies.

    Hook System (ADR-006):
    - Always includes built-in hooks (metrics, logging, latency)
    - Supports additional custom hooks via hooks parameter
    - Hooks receive PagerDutyApiCallContext with method, verb, instance

    Example:
        >>> def rate_limit_hook(ctx: PagerDutyApiCallContext) -> None:
        ...     # Rate limiting logic
        ...     pass
        >>> api = PagerDutyApi(
        ...     id="app-sre",
        ...     token="...",
        ...     hooks=Hooks(pre_hooks=[rate_limit_hook])
        ... )
        >>> users = api.get_schedule_users("ABC123")
        >>> for user in users:
        ...     print(user.org_username)
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        id: str,  # noqa: A002
        token: str,
        timeout: int = TIMEOUT,
        hooks: Hooks | None = None,  # noqa: ARG002 - Handled by @with_hooks decorator
    ) -> None:
        """Initialize PagerDuty API client.

        Args:
            id: PagerDuty ID (for logging, metrics and cache keys)
            token: PagerDuty API token
            timeout: API request timeout in seconds (default: 30)
            hooks: Optional custom hooks to merge with built-in hooks.
                Built-in hooks (metrics, logging, latency) are automatically included.
        """
        self.id = id
        self._timeout = timeout

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
