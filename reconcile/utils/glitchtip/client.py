from reconcile.utils.glitchtip.models import (
    Organization,
    Project,
    ProjectAlert,
    ProjectKey,
    Team,
    User,
)
from reconcile.utils.rest_api_base import ApiBase


class GlitchtipClient(ApiBase):
    def organizations(self) -> list[Organization]:
        """List organizations."""
        return [
            Organization(**r)
            for r in self._list("/api/0/organizations/", params={"limit": 100})
        ]

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
            for r in self._list(
                f"/api/0/organizations/{organization_slug}/teams/",
                params={"limit": 100},
            )
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
            for r in self._list(
                f"/api/0/organizations/{organization_slug}/projects/",
                params={"limit": 100},
            )
        ]

    def create_project(
        self, organization_slug: str, team_slug: str, name: str, platform: str | None
    ) -> Project:
        """Create a project."""
        return Project(
            **self._post(
                f"/api/0/teams/{organization_slug}/{team_slug}/projects/",
                data={"name": name, "platform": platform},
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
        """Update a project."""
        return Project(
            **self._put(
                f"/api/0/projects/{organization_slug}/{slug}/",
                data={
                    "name": name,
                    "platform": platform,
                    "eventThrottleRate": event_throttle_rate,
                },
            )
        )

    def delete_project(self, organization_slug: str, slug: str) -> None:
        """Delete a project."""
        self._delete(
            f"/api/0/projects/{organization_slug}/{slug}/",
        )

    def project_key(self, organization_slug: str, project_slug: str) -> ProjectKey:
        """Retrieve project key (DSN)."""
        keys = self._list(
            f"/api/0/projects/{organization_slug}/{project_slug}/keys/",
            params={"limit": 100},
        )
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
                f"/api/0/projects/{organization_slug}/{project_slug}/alerts/",
                params={"limit": 100},
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
            for r in self._list(
                f"/api/0/organizations/{organization_slug}/members/",
                params={"limit": 100},
            )
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
                f"/api/0/teams/{organization_slug}/{team_slug}/members/",
                params={"limit": 100},
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
