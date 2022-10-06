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

    def organizations(self) -> list[Organization]:
        """List organizations."""
        return [Organization(**r) for r in self._list("/api/0/organizations")]

    def teams(self, organization_slug: str) -> list[Team]:
        """List teams."""
        return [
            Team(**r)
            for r in self._list(f"/api/0/organizations/{organization_slug}/teams/")
        ]

    def projects(self, organization_slug: str) -> list[Project]:
        """List projects."""
        return [
            Project(**r)
            for r in self._list(f"/api/0/organizations/{organization_slug}/projects/")
        ]

    def organization_users(self, organization_slug: str) -> list[User]:
        """List organization users (aka members)."""
        return [
            User(**r)
            for r in self._list(f"/api/0/organizations/{organization_slug}/members/")
        ]

    def team_users(self, organization_slug: str, team_slug: str) -> list[User]:
        """List team users (aka members)."""
        return [
            User(**r)
            for r in self._list(
                f"/api/0/teams/{organization_slug}/{team_slug}/members/"
            )
        ]
