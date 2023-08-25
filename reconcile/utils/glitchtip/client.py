import threading
from typing import (
    Any,
    Optional,
)
from urllib.parse import urljoin

import requests

from reconcile.utils.glitchtip.models import (
    Organization,
    Project,
    ProjectAlert,
    ProjectKey,
    Team,
    User,
)


def get_next_url(links: dict[str, dict[str, str]]) -> Optional[str]:
    """Parse glitchtip's response header 'Link' attribute and return the next page url if exists.

    See
    * https://gitlab.com/glitchtip/glitchtip-backend/-/blob/master/glitchtip/pagination.py#L34
    * https://requests.readthedocs.io/en/latest/api/?highlight=links#requests.Response.links
    """
    if links.get("next", {}).get("results", "false") == "true":
        return links["next"]["url"]
    return None


class GlitchtipClient:  # pylint: disable=too-many-public-methods
    def __init__(
        self, host: str, token: str, max_retries: int = 3, read_timeout: float = 30
    ) -> None:
        self.host = host
        self.token = token
        self.max_retries = max_retries
        self.read_timeout = read_timeout
        self._thread_local = threading.local()

    @property
    def _session(self) -> requests.Session:
        try:
            return self._thread_local.session
        except AttributeError:
            # todo timeout
            self._thread_local.session = requests.Session()
            self._thread_local.session.mount(
                "https://", requests.adapters.HTTPAdapter(max_retries=self.max_retries)
            )
            self._thread_local.session.mount(
                "http://", requests.adapters.HTTPAdapter(max_retries=self.max_retries)
            )
            self._thread_local.session.headers.update(
                {
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                }
            )
            return self._thread_local.session

    def _get(self, url: str) -> dict[str, Any]:
        response = self._session.get(urljoin(self.host, url), timeout=self.read_timeout)
        return response.json()

    def _list(self, url: str, limit: int = 100) -> list[dict[str, Any]]:
        response = self._session.get(
            urljoin(self.host, url), params={"limit": limit}, timeout=self.read_timeout
        )
        response.raise_for_status()
        results = response.json()
        # handle pagination
        while next_url := get_next_url(response.links):
            response = self._session.get(next_url)
            results += response.json()
        return results

    def _post(self, url: str, data: Optional[dict[Any, Any]] = None) -> dict[str, Any]:
        response = self._session.post(
            urljoin(self.host, url), json=data, timeout=self.read_timeout
        )
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json()

    def _put(self, url: str, data: Optional[dict[Any, Any]] = None) -> dict[str, Any]:
        response = self._session.put(
            urljoin(self.host, url), json=data, timeout=self.read_timeout
        )
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        return response.json()

    def _delete(self, url: str) -> None:
        response = self._session.delete(urljoin(self.host, url), timeout=None)
        response.raise_for_status()

    def organizations(self) -> list[Organization]:
        """List organizations."""
        return [Organization(**r) for r in self._list("/api/0/organizations/")]

    def create_organization(self, name: str) -> Organization:
        """Create an organization."""
        return Organization(**self._post("/api/0/organizations/", data={"name": name}))

    def delete_organization(self, slug: str) -> None:
        """Delete an organization."""
        self._delete(f"/api/0/organizations/{slug}/")

    def teams(self, organization_slug: str) -> list[Team]:
        """List teams."""
        return [
            Team(**r)
            for r in self._list(f"/api/0/organizations/{organization_slug}/teams/")
        ]

    def create_team(self, organization_slug: str, slug: str) -> Team:
        """Create a team."""
        return Team(
            **self._post(
                f"/api/0/organizations/{organization_slug}/teams/", data={"slug": slug}
            )
        )

    def delete_team(self, organization_slug: str, slug: str) -> None:
        """Delete a team."""
        self._delete(f"/api/0/teams/{organization_slug}/{slug}/")

    def projects(self, organization_slug: str) -> list[Project]:
        """List projects."""
        return [
            Project(**r)
            for r in self._list(f"/api/0/organizations/{organization_slug}/projects/")
        ]

    def create_project(
        self, organization_slug: str, team_slug: str, name: str, platform: Optional[str]
    ) -> Project:
        """Create a project."""
        return Project(
            **self._post(
                f"/api/0/teams/{organization_slug}/{team_slug}/projects/",
                data={"name": name, "platform": platform},
            )
        )

    def update_project(
        self, organization_slug: str, slug: str, name: str, platform: Optional[str]
    ) -> Project:
        """Update a project."""
        return Project(
            **self._put(
                f"/api/0/projects/{organization_slug}/{slug}/",
                data={"name": name, "platform": platform},
            )
        )

    def delete_project(self, organization_slug: str, slug: str) -> None:
        """Delete a project."""
        self._delete(
            f"/api/0/projects/{organization_slug}/{slug}/",
        )

    def project_key(self, organization_slug: str, project_slug: str) -> ProjectKey:
        """Retrieve project key (DSN)."""
        keys = self._list(f"/api/0/projects/{organization_slug}/{project_slug}/keys/")
        if not keys:
            # only happens if org_slug/project_slug does not exist
            raise ValueError(f"No keys found for project {project_slug}")
        # always return the first key
        return ProjectKey(
            dsn=keys[0]["dsn"]["public"], security_endpoint=keys[0]["dsn"]["security"]
        )

    def project_alerts(
        self, organization_slug: str, project_slug: str
    ) -> list[ProjectAlert]:
        """Retrieve project alerts."""
        return [
            ProjectAlert(**r)
            for r in self._list(
                f"/api/0/projects/{organization_slug}/{project_slug}/alerts/"
            )
        ]

    def create_project_alert(
        self, organization_slug: str, project_slug: str, alert: ProjectAlert
    ) -> ProjectAlert:
        """Add an alert to a project."""
        return ProjectAlert(
            **self._post(
                f"/api/0/projects/{organization_slug}/{project_slug}/alerts/",
                data=alert.dict(by_alias=True, exclude_unset=True, exclude_none=True),
            )
        )

    def delete_project_alert(
        self, organization_slug: str, project_slug: str, alert_pk: int
    ) -> None:
        """Delete an alert from a project."""
        self._delete(
            f"/api/0/projects/{organization_slug}/{project_slug}/alerts/{alert_pk}/",
        )

    def update_project_alert(
        self, organization_slug: str, project_slug: str, alert: ProjectAlert
    ) -> ProjectAlert:
        """Update an alert."""
        return ProjectAlert(
            **self._put(
                f"/api/0/projects/{organization_slug}/{project_slug}/alerts/{alert.pk}/",
                data=alert.dict(by_alias=True, exclude_unset=True, exclude_none=True),
            )
        )

    def add_project_to_team(
        self, organization_slug: str, team_slug: str, slug: str
    ) -> Project:
        """Add a project to a team."""
        return Project(
            **self._post(
                f"/api/0/projects/{organization_slug}/{slug}/teams/{team_slug}/"
            )
        )

    def remove_project_from_team(
        self, organization_slug: str, team_slug: str, slug: str
    ) -> None:
        """Remove a project from a team."""
        self._delete(f"/api/0/projects/{organization_slug}/{slug}/teams/{team_slug}/")

    def organization_users(self, organization_slug: str) -> list[User]:
        """List organization users (aka members)."""
        return [
            User(**r)
            for r in self._list(f"/api/0/organizations/{organization_slug}/members/")
        ]

    def invite_user(self, organization_slug: str, email: str, role: str) -> User:
        """Invite an user to an oranization."""
        return User(
            **self._post(
                f"/api/0/organizations/{organization_slug}/members/",
                data={"email": email, "role": role, "teams": []},
            )
        )

    def delete_user(self, organization_slug: str, pk: int) -> None:
        """Delete an user from an oranization."""
        self._delete(f"/api/0/organizations/{organization_slug}/members/{pk}/")

    def update_user_role(self, organization_slug: str, role: str, pk: int) -> User:
        """Update user role in an oranization."""
        return User(
            **self._put(
                f"/api/0/organizations/{organization_slug}/members/{pk}/",
                data={"role": role},
            )
        )

    def team_users(self, organization_slug: str, team_slug: str) -> list[User]:
        """List team users (aka members)."""
        return [
            User(**r)
            for r in self._list(
                f"/api/0/teams/{organization_slug}/{team_slug}/members/"
            )
        ]

    def add_user_to_team(
        self, organization_slug: str, team_slug: str, user_pk: int
    ) -> Team:
        """Add an user to a team."""
        team = Team(
            **self._post(
                f"/api/0/organizations/{organization_slug}/members/{user_pk}/teams/{team_slug}/"
            )
        )
        team.users = self.team_users(organization_slug, team_slug)
        return team

    def remove_user_from_team(
        self, organization_slug: str, team_slug: str, user_pk: int
    ) -> None:
        """Remove an user from a team."""
        self._delete(
            f"/api/0/organizations/{organization_slug}/members/{user_pk}/teams/{team_slug}/"
        )
