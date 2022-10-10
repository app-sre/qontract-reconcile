from typing import Any, Optional
from urllib.parse import urljoin

import requests
from reconcile.utils.glitchtip.models import Organization, Project, Team, User


def get_next_url(links: dict[str, dict[str, str]]) -> Optional[str]:
    """Parse glitchtip's response header 'Link' attribute and return the next page url if exists.

    See
    * https://gitlab.com/glitchtip/glitchtip-backend/-/blob/master/glitchtip/pagination.py#L34
    * https://requests.readthedocs.io/en/latest/api/?highlight=links#requests.Response.links
    """
    if links.get("next", {}).get("results", "false") == "true":
        return links["next"]["url"]
    return None


class GlitchtipClient:
    def __init__(self, host: str, token: str) -> None:
        self.host = host
        # todo timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )

    def _get(self, url: str) -> dict[str, Any]:
        response = self._session.get(urljoin(self.host, url))
        return response.json()

    def _list(self, url: str, limit: int = 100) -> list[dict[str, Any]]:
        response = self._session.get(urljoin(self.host, url), params={"limit": limit})
        results = response.json()
        # handle pagination
        while next_url := get_next_url(response.links):
            response = self._session.get(next_url)
            results += response.json()
        return results

    def _post(self, url: str, data: Optional[dict[Any, Any]] = None) -> dict[str, Any]:
        response = self._session.post(urljoin(self.host, url), json=data)
        if response.status_code == 204:
            return {}
        return response.json()

    def _put(self, url: str, data: Optional[dict[Any, Any]] = None) -> dict[str, Any]:
        response = self._session.put(urljoin(self.host, url), json=data)
        if response.status_code == 204:
            return {}
        return response.json()

    def _delete(self, url: str) -> None:
        self._session.delete(urljoin(self.host, url))

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
        self, organization_slug: str, team_slug: str, name: str
    ) -> Project:
        """Create a project."""
        return Project(
            **self._post(
                f"/api/0/teams/{organization_slug}/{team_slug}/projects/",
                data={"name": name},
            )
        )

    def delete_project(self, organization_slug: str, team_slug: str, slug: str) -> None:
        """Delete a project."""
        self._delete(
            f"/api/0/teams/{organization_slug}/{team_slug}/projects/{slug}/",
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

    def delete_project_from_team(
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

    def add_user_to_team(self, organization_slug: str, team_slug: str, pk: int) -> Team:
        """Add an user to a team."""
        team = Team(
            **self._post(
                f"/api/0/organizations/{organization_slug}/members/{pk}/teams/{team_slug}/"
            )
        )
        team.users = self.team_users(organization_slug, team_slug)
        return team

    def delete_user_from_team(
        self, organization_slug: str, team_slug: str, pk: int
    ) -> None:
        """Remove an user from a team."""
        self._delete(
            f"/api/0/organizations/{organization_slug}/members/{pk}/teams/{team_slug}/"
        )
