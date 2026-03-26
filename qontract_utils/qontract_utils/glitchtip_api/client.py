"""Glitchtip API client with hook system.

Following ADR-014 (Three-Layer Architecture) - Layer 1: Pure Communication.
This module provides a stateless API client with support for metrics and
rate limiting via hooks (ADR-006).
"""

import contextvars
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from prometheus_client import Counter, Histogram

from qontract_utils.glitchtip_api.models import (
    Organization,
    Project,
    ProjectAlert,
    Team,
    User,
)
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks
from qontract_utils.metrics import DEFAULT_BUCKETS_EXTERNAL_API

logger = structlog.get_logger(__name__)

# Prometheus metrics
glitchtip_request = Counter(
    # Following naming convention (qontract_reconcile_external_api_<component>_requests_total) to
    # automatically include this metric in dashboards
    "qontract_reconcile_external_api_glitchtip_requests_total",
    "Total number of Glitchtip API requests",
    ["method", "verb"],
)

glitchtip_request_duration = Histogram(
    "qontract_reconcile_external_api_glitchtip_request_duration_seconds",
    "Glitchtip API request duration in seconds",
    ["method", "verb"],
    buckets=DEFAULT_BUCKETS_EXTERNAL_API,
)

# Local storage for latency tracking (tuple stack to support nested calls)
_latency_tracker: contextvars.ContextVar[tuple[float, ...]] = contextvars.ContextVar(
    f"{__name__}.latency_tracker", default=()
)

TIMEOUT = 30


@dataclass(frozen=True)
class GlitchtipApiCallContext:
    """Context information passed to API call hooks.

    Attributes:
        method: API method name (e.g., "organizations.list")
        verb: HTTP verb (e.g., "GET")
        id: Glitchtip instance identifier (host URL)
    """

    method: str
    verb: str
    id: str


def _metrics_hook(context: GlitchtipApiCallContext) -> None:
    """Built-in Prometheus metrics hook."""
    glitchtip_request.labels(context.method, context.verb).inc()


def _latency_start_hook(_context: GlitchtipApiCallContext) -> None:
    """Built-in hook to start latency measurement."""
    _latency_tracker.set((*_latency_tracker.get(), time.perf_counter()))


def _latency_end_hook(context: GlitchtipApiCallContext) -> None:
    """Built-in hook to record latency measurement."""
    stack = _latency_tracker.get()
    if not stack:
        return
    start_time = stack[-1]
    _latency_tracker.set(stack[:-1])
    duration = time.perf_counter() - start_time
    glitchtip_request_duration.labels(context.method, context.verb).observe(duration)


def _request_log_hook(context: GlitchtipApiCallContext) -> None:
    """Built-in hook for logging API requests."""
    logger.debug("API request", method=context.method, verb=context.verb, id=context.id)


def parse_link_header(link_header: str) -> dict[str, dict[str, str]]:
    """Parse RFC 5988 Link header into dict keyed by rel.

    Args:
        link_header: Raw Link header value

    Returns:
        Dict mapping rel to a dict of attributes including "url"

    Example:
        >>> parse_link_header('<https://host/next?cursor=abc>; rel="next"; results="true"')
        {'next': {'url': 'https://host/next?cursor=abc', 'rel': 'next', 'results': 'true'}}
    """
    result: dict[str, dict[str, str]] = {}
    if not link_header:
        return result
    for part in link_header.split(","):
        parts = [p.strip() for p in part.strip().split(";")]
        if not parts:
            continue
        url = parts[0].strip("<>")
        attrs: dict[str, str] = {"url": url}
        for attr in parts[1:]:
            if "=" in attr:
                k, v = attr.split("=", 1)
                attrs[k.strip()] = v.strip().strip('"')
        rel = attrs.get("rel", "")
        if rel:
            result[rel] = attrs
    return result


def get_next_url(response: httpx.Response) -> str | None:
    """Get next page URL from Link header if it has results.

    Args:
        response: httpx response with Link header

    Returns:
        Next page URL if available, None otherwise
    """
    link_header = response.headers.get("Link", "")
    links = parse_link_header(link_header)
    next_link = links.get("next", {})
    if next_link.get("results", "false") == "true":
        return next_link.get("url")
    return None


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
class GlitchtipApi:
    """Stateless Glitchtip API client with hook system.

    Layer 1 (Pure Communication) client following ADR-014. Provides methods
    to manage organizations, projects, and project alerts in Glitchtip.

    Hook System (ADR-006):
    - Always includes built-in hooks (metrics, logging, latency)
    - Supports additional custom hooks via hooks parameter
    - Hooks receive GlitchtipApiCallContext with method, verb, id

    Example:
        >>> api = GlitchtipApi(host="https://glitchtip.example.com", token="...")
        >>> orgs = api.organizations()
        >>> for org in orgs:
        ...     print(org.name)
    """

    # Set by @with_hooks decorator
    _hooks: Hooks

    def __init__(
        self,
        host: str,
        token: str,
        timeout: int = TIMEOUT,
        max_retries: int = 3,
        hooks: Hooks | None = None,  # noqa: ARG002 - Handled by @with_hooks decorator
    ) -> None:
        """Initialize Glitchtip API client.

        Args:
            host: Glitchtip instance host URL (e.g., "https://glitchtip.example.com")
            token: Glitchtip API token (Bearer token)
            timeout: API request timeout in seconds (default: 30)
            max_retries: Number of retries for failed requests (default: 3)
            hooks: Optional custom hooks to merge with built-in hooks.
                Built-in hooks (metrics, logging, latency) are automatically included.
        """
        self.host = host.rstrip("/")
        self._client = httpx.Client(
            base_url=self.host,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=httpx.HTTPTransport(retries=max_retries),
        )

    def _list(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated endpoint.

        Args:
            path: API path (e.g., "/api/0/organizations/")
            params: Optional query parameters

        Returns:
            Flat list of all items across all pages
        """
        results: list[dict[str, Any]] = []
        url: str | None = path
        while url:
            response = self._client.get(url, params=params if url == path else None)
            response.raise_for_status()
            results.extend(response.json())
            url = get_next_url(response)
        return results

    def _post(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST request to API.

        Args:
            path: API path
            data: JSON request body

        Returns:
            Response JSON as dict
        """
        response = self._client.post(path, json=data or {})
        response.raise_for_status()
        return response.json()

    def _put(self, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """PUT request to API.

        Args:
            path: API path
            data: JSON request body

        Returns:
            Response JSON as dict
        """
        response = self._client.put(path, json=data or {})
        response.raise_for_status()
        return response.json()

    def _delete(self, path: str) -> None:
        """DELETE request to API.

        Args:
            path: API path
        """
        response = self._client.delete(path)
        response.raise_for_status()

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="organizations.list", verb="GET", id=self.host
        )
    )
    def organizations(self) -> list[Organization]:
        """List all organizations.

        Returns:
            List of Organization objects

        Example:
            >>> api = GlitchtipApi(host="https://glitchtip.example.com", token="...")
            >>> orgs = api.organizations()
            >>> print([o.name for o in orgs])
            ['my-org']
        """
        return [
            Organization.model_validate(r)
            for r in self._list("/api/0/organizations/", params={"limit": 100})
        ]

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="projects.list", verb="GET", id=self.host
        )
    )
    def projects(self, organization_slug: str) -> list[Project]:
        """List projects in an organization.

        Args:
            organization_slug: Organization slug

        Returns:
            List of Project objects

        Example:
            >>> api = GlitchtipApi(host="https://glitchtip.example.com", token="...")
            >>> projects = api.projects("my-org")
            >>> print([p.slug for p in projects])
            ['my-project']
        """
        return [
            Project.model_validate(r)
            for r in self._list(
                f"/api/0/organizations/{organization_slug}/projects/",
                params={"limit": 100},
            )
        ]

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="project_alerts.list", verb="GET", id=self.host
        )
    )
    def project_alerts(
        self, organization_slug: str, project_slug: str
    ) -> list[ProjectAlert]:
        """List alerts for a project.

        Args:
            organization_slug: Organization slug
            project_slug: Project slug

        Returns:
            List of ProjectAlert objects

        Example:
            >>> api = GlitchtipApi(host="https://glitchtip.example.com", token="...")
            >>> alerts = api.project_alerts("my-org", "my-project")
            >>> print([a.name for a in alerts])
            ['high-error-rate']
        """
        return [
            ProjectAlert.model_validate(r)
            for r in self._list(
                f"/api/0/projects/{organization_slug}/{project_slug}/alerts/",
                params={"limit": 100},
            )
        ]

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="project_alerts.create", verb="POST", id=self.host
        )
    )
    def create_project_alert(
        self, organization_slug: str, project_slug: str, alert: ProjectAlert
    ) -> ProjectAlert:
        """Create a new alert for a project.

        Args:
            organization_slug: Organization slug
            project_slug: Project slug
            alert: ProjectAlert to create (pk will be ignored)

        Returns:
            Created ProjectAlert with pk set by API

        Example:
            >>> api = GlitchtipApi(host="https://glitchtip.example.com", token="...")
            >>> alert = ProjectAlert(
            ...     name="high-error-rate",
            ...     timespan_minutes=1,
            ...     quantity=100,
            ...     recipients=[ProjectAlertRecipient(
            ...         recipient_type=RecipientType.EMAIL, url=""
            ...     )],
            ... )
            >>> created = api.create_project_alert("my-org", "my-project", alert)
        """
        data = _alert_to_dict(alert)
        return ProjectAlert.model_validate(
            self._post(
                f"/api/0/projects/{organization_slug}/{project_slug}/alerts/",
                data=data,
            )
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="project_alerts.update", verb="PUT", id=self.host
        )
    )
    def update_project_alert(
        self, organization_slug: str, project_slug: str, alert: ProjectAlert
    ) -> ProjectAlert:
        """Update an existing project alert.

        Args:
            organization_slug: Organization slug
            project_slug: Project slug
            alert: ProjectAlert to update (must have pk set)

        Returns:
            Updated ProjectAlert

        Raises:
            ValueError: If alert.pk is None
        """
        if alert.pk is None:
            raise ValueError("Cannot update alert without pk")
        data = _alert_to_dict(alert)
        return ProjectAlert.model_validate(
            self._put(
                f"/api/0/projects/{organization_slug}/{project_slug}/alerts/{alert.pk}/",
                data=data,
            )
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="project_alerts.delete", verb="DELETE", id=self.host
        )
    )
    def delete_project_alert(
        self, organization_slug: str, project_slug: str, alert_pk: int
    ) -> None:
        """Delete a project alert.

        Args:
            organization_slug: Organization slug
            project_slug: Project slug
            alert_pk: Primary key of alert to delete

        Example:
            >>> api = GlitchtipApi(host="https://glitchtip.example.com", token="...")
            >>> api.delete_project_alert("my-org", "my-project", 42)
        """
        self._delete(
            f"/api/0/projects/{organization_slug}/{project_slug}/alerts/{alert_pk}/"
        )

    # --- Organizations ---

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="organizations.create", verb="POST", id=self.host
        )
    )
    def create_organization(self, name: str) -> Organization:
        """Create a new organization.

        Args:
            name: Organization name

        Returns:
            Created Organization
        """
        return Organization.model_validate(
            self._post("/api/0/organizations/", data={"name": name})
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="organizations.delete", verb="DELETE", id=self.host
        )
    )
    def delete_organization(self, slug: str) -> None:
        """Delete an organization.

        Args:
            slug: Organization slug
        """
        self._delete(f"/api/0/organizations/{slug}/")

    # --- Teams ---

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="teams.list", verb="GET", id=self.host
        )
    )
    def teams(self, organization_slug: str) -> list[Team]:
        """List teams in an organization.

        Args:
            organization_slug: Organization slug

        Returns:
            List of Team objects
        """
        return [
            Team.model_validate(r)
            for r in self._list(
                f"/api/0/organizations/{organization_slug}/teams/",
                params={"limit": 100},
            )
        ]

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="teams.create", verb="POST", id=self.host
        )
    )
    def create_team(self, organization_slug: str, slug: str) -> Team:
        """Create a team in an organization.

        Args:
            organization_slug: Organization slug
            slug: Team slug

        Returns:
            Created Team
        """
        return Team.model_validate(
            self._post(
                f"/api/0/organizations/{organization_slug}/teams/",
                data={"slug": slug},
            )
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="teams.delete", verb="DELETE", id=self.host
        )
    )
    def delete_team(self, organization_slug: str, slug: str) -> None:
        """Delete a team.

        Args:
            organization_slug: Organization slug
            slug: Team slug
        """
        self._delete(f"/api/0/teams/{organization_slug}/{slug}/")

    # --- Projects (extended CRUD) ---

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="projects.create", verb="POST", id=self.host
        )
    )
    def create_project(
        self,
        organization_slug: str,
        team_slug: str,
        name: str,
        platform: str | None,
    ) -> Project:
        """Create a project under a team.

        Args:
            organization_slug: Organization slug
            team_slug: Team slug (project is initially assigned to this team)
            name: Project name
            platform: Project platform (e.g., "python")

        Returns:
            Created Project
        """
        return Project.model_validate(
            self._post(
                f"/api/0/teams/{organization_slug}/{team_slug}/projects/",
                data={"name": name, "platform": platform},
            )
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="projects.update", verb="PUT", id=self.host
        )
    )
    def update_project(
        self,
        organization_slug: str,
        slug: str,
        name: str,
        platform: str | None,
        event_throttle_rate: int,
    ) -> Project:
        """Update a project.

        Args:
            organization_slug: Organization slug
            slug: Project slug
            name: New project name
            platform: New platform
            event_throttle_rate: New event throttle rate

        Returns:
            Updated Project
        """
        return Project.model_validate(
            self._put(
                f"/api/0/projects/{organization_slug}/{slug}/",
                data={
                    "name": name,
                    "platform": platform,
                    "eventThrottleRate": event_throttle_rate,
                },
            )
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="projects.delete", verb="DELETE", id=self.host
        )
    )
    def delete_project(self, organization_slug: str, slug: str) -> None:
        """Delete a project.

        Args:
            organization_slug: Organization slug
            slug: Project slug
        """
        self._delete(f"/api/0/projects/{organization_slug}/{slug}/")

    # --- Project-Team associations ---

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="projects.add_team", verb="POST", id=self.host
        )
    )
    def add_project_to_team(
        self, organization_slug: str, project_slug: str, team_slug: str
    ) -> Project:
        """Add a project to a team.

        Args:
            organization_slug: Organization slug
            project_slug: Project slug
            team_slug: Team slug

        Returns:
            Updated Project
        """
        return Project.model_validate(
            self._post(
                f"/api/0/projects/{organization_slug}/{project_slug}/teams/{team_slug}/"
            )
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="projects.remove_team", verb="DELETE", id=self.host
        )
    )
    def remove_project_from_team(
        self, organization_slug: str, project_slug: str, team_slug: str
    ) -> None:
        """Remove a project from a team.

        Args:
            organization_slug: Organization slug
            project_slug: Project slug
            team_slug: Team slug
        """
        self._delete(
            f"/api/0/projects/{organization_slug}/{project_slug}/teams/{team_slug}/"
        )

    # --- Organization users ---

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="organization_users.list", verb="GET", id=self.host
        )
    )
    def organization_users(self, organization_slug: str) -> list[User]:
        """List organization members.

        Args:
            organization_slug: Organization slug

        Returns:
            List of User objects
        """
        return [
            User.model_validate(r)
            for r in self._list(
                f"/api/0/organizations/{organization_slug}/members/",
                params={"limit": 100},
            )
        ]

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="organization_users.invite", verb="POST", id=self.host
        )
    )
    def invite_user(self, organization_slug: str, email: str, role: str) -> User:
        """Invite a user to an organization.

        Args:
            organization_slug: Organization slug
            email: User email address
            role: Organization role (e.g., "member", "admin")

        Returns:
            Created User (invitation pending)
        """
        return User.model_validate(
            self._post(
                f"/api/0/organizations/{organization_slug}/members/",
                data={
                    "email": email,
                    "send_invite": False,
                    "orgRole": role,
                    "teamRoles": [],
                },
            )
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="organization_users.delete", verb="DELETE", id=self.host
        )
    )
    def delete_user(self, organization_slug: str, pk: int) -> None:
        """Remove a user from an organization.

        Args:
            organization_slug: Organization slug
            pk: User primary key
        """
        self._delete(f"/api/0/organizations/{organization_slug}/members/{pk}/")

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="organization_users.update_role", verb="PUT", id=self.host
        )
    )
    def update_user_role(self, organization_slug: str, pk: int, role: str) -> User:
        """Update a user's role in an organization.

        Args:
            organization_slug: Organization slug
            pk: User primary key
            role: New role (e.g., "member", "admin")

        Returns:
            Updated User
        """
        return User.model_validate(
            self._put(
                f"/api/0/organizations/{organization_slug}/members/{pk}/",
                data={"orgRole": role},
            )
        )

    # --- Team users ---

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="team_users.list", verb="GET", id=self.host
        )
    )
    def team_users(self, organization_slug: str, team_slug: str) -> list[User]:
        """List members of a team.

        Args:
            organization_slug: Organization slug
            team_slug: Team slug

        Returns:
            List of User objects
        """
        return [
            User.model_validate(r)
            for r in self._list(
                f"/api/0/teams/{organization_slug}/{team_slug}/members/",
                params={"limit": 100},
            )
        ]

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="team_users.add", verb="POST", id=self.host
        )
    )
    def add_user_to_team(
        self, organization_slug: str, team_slug: str, user_pk: int
    ) -> None:
        """Add a user to a team.

        Args:
            organization_slug: Organization slug
            team_slug: Team slug
            user_pk: User primary key
        """
        self._post(
            f"/api/0/organizations/{organization_slug}/members/{user_pk}/teams/{team_slug}/"
        )

    @invoke_with_hooks(
        lambda self: GlitchtipApiCallContext(
            method="team_users.remove", verb="DELETE", id=self.host
        )
    )
    def remove_user_from_team(
        self, organization_slug: str, team_slug: str, user_pk: int
    ) -> None:
        """Remove a user from a team.

        Args:
            organization_slug: Organization slug
            team_slug: Team slug
            user_pk: User primary key
        """
        self._delete(
            f"/api/0/organizations/{organization_slug}/members/{user_pk}/teams/{team_slug}/"
        )

    def close(self) -> None:
        """Close the underlying httpx client."""
        self._client.close()

    def __enter__(self) -> "GlitchtipApi":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _alert_to_dict(alert: ProjectAlert) -> dict[str, Any]:
    """Convert ProjectAlert to API request dict (camelCase aliases).

    Args:
        alert: ProjectAlert to serialize

    Returns:
        Dict with camelCase keys for Glitchtip API
    """
    return {
        "name": alert.name,
        "timespanMinutes": alert.timespan_minutes,
        "quantity": alert.quantity,
        "alertRecipients": [
            {
                "recipientType": r.recipient_type.value,
                **({"url": r.url} if r.url else {}),
            }
            for r in alert.recipients
        ],
    }
