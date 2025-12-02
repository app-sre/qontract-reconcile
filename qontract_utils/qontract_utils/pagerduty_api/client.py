"""PagerDuty API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
rate limiting via hooks (ADR-006).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pagerduty import RestApiV2Client
from prometheus_client import Counter

from qontract_utils.pagerduty_api.models import PagerDutyUser

# Prometheus metrics
pagerduty_request = Counter(
    "qontract_pagerduty_api_requests_total",
    "Total number of PagerDuty API requests",
    ["method", "verb"],
)

TIMEOUT = 30
TIME_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class PagerDutyApiCallContext:
    """Context passed to before_api_call hooks.

    Attributes:
        method: API method name (e.g., "schedules.get")
        verb: HTTP verb (e.g., "GET")
        instance: PagerDuty instance name
    """

    method: str
    verb: str
    instance: str


def _metrics_hook(context: PagerDutyApiCallContext) -> None:
    """Built-in Prometheus metrics hook.

    Records all API calls with method and verb labels.
    """
    pagerduty_request.labels(context.method, context.verb).inc()


class PagerDutyApi:
    """Stateless PagerDuty API client with hook system.

    Layer 1 (Pure Communication) client following ADR-014. Provides methods
    to fetch users from PagerDuty schedules and escalation policies.

    Hook System (ADR-006):
    - Always includes metrics hook for Prometheus
    - Supports additional hooks via before_api_call_hooks parameter
    - Hooks receive PagerDutyApiCallContext with method, verb, instance

    Example:
        >>> def rate_limit_hook(ctx: PagerDutyApiCallContext) -> None:
        ...     # Rate limiting logic
        ...     pass
        >>> api = PagerDutyApi(
        ...     instance_name="app-sre",
        ...     token="...",
        ...     before_api_call_hooks=[rate_limit_hook]
        ... )
        >>> users = api.get_schedule_users("ABC123")
        >>> for user in users:
        ...     print(user.org_username)
    """

    def __init__(
        self,
        instance_name: str,
        token: str,
        timeout: int = TIMEOUT,
        before_api_call_hooks: Sequence[Callable[[PagerDutyApiCallContext], None]]
        | None = None,
    ) -> None:
        """Initialize PagerDuty API client.

        Args:
            instance_name: PagerDuty instance name (for logging/metrics)
            token: PagerDuty API token
            timeout: API request timeout in seconds (default: 30)
            before_api_call_hooks: Optional hooks called before API requests
        """
        self.instance_name = instance_name
        self._timeout = timeout

        # Setup hook system - always include metrics hook
        self._before_api_call_hooks: list[Callable[[PagerDutyApiCallContext], None]] = [
            _metrics_hook
        ]
        if before_api_call_hooks:
            self._before_api_call_hooks.extend(before_api_call_hooks)

        # Initialize PagerDuty client
        self._client = RestApiV2Client(api_key=token)

    def _call_hooks(self, method: str, verb: str) -> None:
        """Call all registered hooks before API call.

        Args:
            method: API method name (e.g., "schedules.get")
            verb: HTTP verb (e.g., "GET")
        """
        context = PagerDutyApiCallContext(
            method=method,
            verb=verb,
            instance=self.instance_name,
        )
        for hook in self._before_api_call_hooks:
            hook(context)

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
        self._call_hooks("users.get", "GET")
        user_data = self._client.rget(f"/users/{user_id}")  # type: ignore[misc]
        return PagerDutyUser(
            id=user_id,
            email=user_data["email"],
            name=user_data["name"],
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
        self._call_hooks("schedules.get", "GET")

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
        self._call_hooks("escalation_policies.get", "GET")
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
