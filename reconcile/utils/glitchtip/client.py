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
        """List organizations.

        REST API response example:
        [{
            "id": 10,
            "name": "ESA",
            "slug": "esa",
            "dateCreated": "2022-09-13T12:01:05.186161Z",
            "status": {
                "id": "active",
                "name": "active"
                },
            "avatar": {
                "avatarType": "",
                "avatarUuid": null
                },
            "isEarlyAdopter": false,
            "require2FA": false,
            "isAcceptingEvents": true
        },]
        """
        return [Organization(**r) for r in self._list("/api/0/organizations")]

    def teams(self, organization: Organization) -> list[Team]:
        """List teams.

        REST API response example:
        [{
            "dateCreated": "2022-09-20T11:52:00.382966Z",
            "id": "5",
            "isMember": true,
            "memberCount": 1,
            "slug": "pilots"
        },]
        """
        return [
            Team(**r)
            for r in self._list(f"/api/0/organizations/{organization.slug}/teams/")
        ]

    def projects(self, organization: Organization) -> list[Project]:
        """List projects.

        Note: project.team.users is an empty list because it isn't returned by the API.

        REST API response example:
        [{
            "avatar": {
                "avatarType": "",
                "avatarUuid": null
            },
            "color": "",
            "features": [],
            "firstEvent": null,
            "hasAccess": true,
            "id": "6",
            "isBookmarked": false,
            "isInternal": false,
            "isMember": true,
            "isPublic": false,
            "name": "apollo-11",
            "organization": {
                "id": 4,
                "name": "NASA",
                "slug": "nasa",
                "dateCreated": "2022-09-13T11:23:23.306148Z",
                "status": {
                    "id": "active",
                    "name": "active"
                },
                "avatar": {
                    "avatarType": "",
                    "avatarUuid": null
                },
                "isEarlyAdopter": false,
                "require2FA": false,
                "isAcceptingEvents": true
            },
            "teams": [
            {
                "id": "5",
                "slug": "pilots"
            }
            ],
            "scrubIPAddresses": true,
            "slug": "apollo-11",
            "dateCreated": "2022-09-19T13:46:05.740945Z",
            "platform": null
        },]
        """
        return [
            Project(**r)
            for r in self._list(f"/api/0/organizations/{organization.slug}/projects/")
        ]

    def organization_users(self, organization: Organization) -> list[User]:
        """List organization users (aka members).

        REST API response example:
        [{
            "role": "member",
            "id": 19,
            "user": {
                "username": "cassing@redhat.com",
                "lastLogin": "2022-09-23T11:16:38.750691Z",
                "isSuperuser": false,
                "emails": [],
                "identities": [],
                "id": "1",
                "isActive": true,
                "name": "",
                "dateJoined": "2022-09-13T10:35:53.988312Z",
                "hasPasswordAuth": true,
                "email": "cassing@redhat.com",
                "options": {}
            },
            "roleName": "Member",
            "dateCreated": "2022-09-20T10:25:43.908164Z",
            "email": "cassing@redhat.com",
            "pending": false
        },]
        """
        return [
            User(**r)
            for r in self._list(f"/api/0/organizations/{organization.slug}/members/")
        ]

    def team_users(self, organization: Organization, team: Team) -> list[User]:
        """List team users (aka members).

        REST API response example:

        [{
          "role": "owner",
          "id": 5,
          "user": {
            "username": "sd-app-sre+glitchtip@redhat.com",
            "lastLogin": "2022-09-21T11:08:20.306968Z",
            "isSuperuser": false,
            "emails": [],
            "identities": [],
            "id": "3",
            "isActive": true,
            "name": "",
            "dateJoined": "2022-09-13T10:58:07.053773Z",
            "hasPasswordAuth": true,
            "email": "sd-app-sre+glitchtip@redhat.com",
            "options": "{}"
          },
          "roleName": "Owner",
          "dateCreated": "2022-09-13T11:23:23.313535Z",
          "email": "sd-app-sre+glitchtip@redhat.com",
          "pending": false
        },]
        """
        return [
            User(**r)
            for r in self._list(
                f"/api/0/teams/{organization.slug}/{team.slug}/members/"
            )
        ]
