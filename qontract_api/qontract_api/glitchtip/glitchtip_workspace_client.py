"""GlitchtipWorkspaceClient: Caching + compute layer for Glitchtip data.

This layer sits between the stateless GlitchtipApi and business logic, providing:
- Two-tier caching (memory + Redis) for Glitchtip data
- Distributed locking for thread-safe cache updates
- Write-through cache invalidation after mutations
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from qontract_utils.glitchtip_api import GlitchtipApi
from qontract_utils.glitchtip_api.models import (
    Organization,
    Project,
    ProjectAlert,
    Team,
    User,
)

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedOrganizations(BaseModel, frozen=True):
    """Cached list of Organization objects (for two-tier cache serialization)."""

    items: list[Organization] = Field(default_factory=list)


class CachedProjects(BaseModel, frozen=True):
    """Cached list of Project objects (for two-tier cache serialization)."""

    items: list[Project] = Field(default_factory=list)


class CachedProjectAlerts(BaseModel, frozen=True):
    """Cached list of ProjectAlert objects (for two-tier cache serialization)."""

    items: list[ProjectAlert] = Field(default_factory=list)


class CachedTeams(BaseModel, frozen=True):
    """Cached list of Team objects (for two-tier cache serialization)."""

    items: list[Team] = Field(default_factory=list)


class CachedUsers(BaseModel, frozen=True):
    """Cached list of User objects (for two-tier cache serialization)."""

    items: list[User] = Field(default_factory=list)


class GlitchtipWorkspaceClient:
    """Caching + compute layer for Glitchtip data.

    Provides:
    - Cached access to organizations, projects, and alerts with TTL
    - Distributed locking for thread-safe cache updates
    - Write-through cache invalidation after mutations
    """

    def __init__(
        self,
        glitchtip_api: GlitchtipApi,
        instance_name: str,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize GlitchtipWorkspaceClient.

        Args:
            glitchtip_api: Stateless Glitchtip API client
            instance_name: Glitchtip instance name (for cache key namespacing)
            cache: Cache backend with two-tier caching (memory + Redis)
            settings: Application settings with Glitchtip config
        """
        self.glitchtip_api = glitchtip_api
        self.instance_name = instance_name
        self.cache = cache
        self.settings = settings

    # CACHE KEY HELPERS
    def _cache_key_organizations(self) -> str:
        return f"glitchtip:{self.instance_name}:organizations"

    def _cache_key_projects(self, org_slug: str) -> str:
        return f"glitchtip:{self.instance_name}:{org_slug}:projects"

    def _cache_key_alerts(self, org_slug: str, project_slug: str) -> str:
        return f"glitchtip:{self.instance_name}:{org_slug}:{project_slug}:alerts"

    def _cache_key_teams(self, org_slug: str) -> str:
        return f"glitchtip:{self.instance_name}:{org_slug}:teams"

    def _cache_key_org_users(self, org_slug: str) -> str:
        return f"glitchtip:{self.instance_name}:{org_slug}:users"

    def _cache_key_team_users(self, org_slug: str, team_slug: str) -> str:
        return f"glitchtip:{self.instance_name}:{org_slug}:{team_slug}:team_users"

    def _clear_cache(self, cache_key: str) -> None:
        """Clear cache for given key."""
        try:
            with self.cache.lock(cache_key):
                self.cache.delete(cache_key)
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock for {cache_key}: {e}")

    # CACHED DATA ACCESS
    def get_organizations(self) -> dict[str, Organization]:
        """Get all organizations (cached with distributed locking).

        Returns:
            Dict of Organization objects keyed by organization name
        """
        cache_key = self._cache_key_organizations()

        if cached := self.cache.get_obj(cache_key, CachedOrganizations):
            return {org.name: org for org in cached.items}

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedOrganizations):
                return {org.name: org for org in cached.items}

            orgs = self.glitchtip_api.organizations()
            self.cache.set_obj(
                cache_key,
                CachedOrganizations(items=orgs),
                self.settings.glitchtip.organizations_cache_ttl,
            )
            return {org.name: org for org in orgs}

    def get_projects(self, org_slug: str) -> list[Project]:
        """Get projects for an organization (cached with distributed locking).

        Args:
            org_slug: Organization slug

        Returns:
            List of Project objects
        """
        cache_key = self._cache_key_projects(org_slug)

        if cached := self.cache.get_obj(cache_key, CachedProjects):
            return cached.items

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedProjects):
                return cached.items

            projects = self.glitchtip_api.projects(org_slug)
            self.cache.set_obj(
                cache_key,
                CachedProjects(items=projects),
                self.settings.glitchtip.projects_cache_ttl,
            )
            return projects

    def get_project_alerts(
        self, org_slug: str, project_slug: str
    ) -> list[ProjectAlert]:
        """Get alerts for a project (cached with distributed locking).

        Args:
            org_slug: Organization slug
            project_slug: Project slug

        Returns:
            List of ProjectAlert objects
        """
        cache_key = self._cache_key_alerts(org_slug, project_slug)

        if cached := self.cache.get_obj(cache_key, CachedProjectAlerts):
            return cached.items

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedProjectAlerts):
                return cached.items

            alerts = self.glitchtip_api.project_alerts(org_slug, project_slug)
            self.cache.set_obj(
                cache_key,
                CachedProjectAlerts(items=alerts),
                self.settings.glitchtip.alerts_cache_ttl,
            )
            return alerts

    # WRITE-THROUGH METHODS (clear cache after mutation)
    def create_project_alert(
        self, org_slug: str, project_slug: str, alert: ProjectAlert
    ) -> ProjectAlert:
        """Create a project alert and clear alert cache.

        Args:
            org_slug: Organization slug
            project_slug: Project slug
            alert: ProjectAlert to create

        Returns:
            Created ProjectAlert with pk set by API
        """
        created = self.glitchtip_api.create_project_alert(org_slug, project_slug, alert)
        self._clear_cache(self._cache_key_alerts(org_slug, project_slug))
        return created

    def update_project_alert(
        self, org_slug: str, project_slug: str, alert: ProjectAlert
    ) -> ProjectAlert:
        """Update a project alert and clear alert cache.

        Args:
            org_slug: Organization slug
            project_slug: Project slug
            alert: ProjectAlert to update (must have pk set)

        Returns:
            Updated ProjectAlert
        """
        updated = self.glitchtip_api.update_project_alert(org_slug, project_slug, alert)
        self._clear_cache(self._cache_key_alerts(org_slug, project_slug))
        return updated

    def delete_project_alert(
        self, org_slug: str, project_slug: str, alert_pk: int
    ) -> None:
        """Delete a project alert and clear alert cache.

        Args:
            org_slug: Organization slug
            project_slug: Project slug
            alert_pk: Primary key of alert to delete
        """
        self.glitchtip_api.delete_project_alert(org_slug, project_slug, alert_pk)
        self._clear_cache(self._cache_key_alerts(org_slug, project_slug))

    # --- Organizations ---

    def create_organization(self, name: str) -> Organization:
        """Create an organization and clear organizations cache."""
        org = self.glitchtip_api.create_organization(name)
        self._clear_cache(self._cache_key_organizations())
        return org

    def delete_organization(self, slug: str) -> None:
        """Delete an organization and clear organizations cache."""
        self.glitchtip_api.delete_organization(slug)
        self._clear_cache(self._cache_key_organizations())

    # --- Teams ---

    def get_teams(self, org_slug: str) -> list[Team]:
        """Get teams for an organization (cached with distributed locking).

        Args:
            org_slug: Organization slug

        Returns:
            List of Team objects
        """
        cache_key = self._cache_key_teams(org_slug)

        if cached := self.cache.get_obj(cache_key, CachedTeams):
            return cached.items

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedTeams):
                return cached.items

            teams = self.glitchtip_api.teams(org_slug)
            self.cache.set_obj(
                cache_key,
                CachedTeams(items=teams),
                self.settings.glitchtip.teams_cache_ttl,
            )
            return teams

    def create_team(self, org_slug: str, slug: str) -> Team:
        """Create a team and clear teams cache."""
        team = self.glitchtip_api.create_team(org_slug, slug)
        self._clear_cache(self._cache_key_teams(org_slug))
        return team

    def delete_team(self, org_slug: str, slug: str) -> None:
        """Delete a team and clear teams and projects cache.

        GlitchTip automatically removes project-team associations when a team
        is deleted, so the projects cache must also be invalidated.
        """
        self.glitchtip_api.delete_team(org_slug, slug)
        self._clear_cache(self._cache_key_teams(org_slug))
        self._clear_cache(self._cache_key_projects(org_slug))

    # --- Organization users ---

    def get_organization_users(self, org_slug: str) -> list[User]:
        """Get organization members (cached with distributed locking).

        Args:
            org_slug: Organization slug

        Returns:
            List of User objects
        """
        cache_key = self._cache_key_org_users(org_slug)

        if cached := self.cache.get_obj(cache_key, CachedUsers):
            return cached.items

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedUsers):
                return cached.items

            users = self.glitchtip_api.organization_users(org_slug)
            self.cache.set_obj(
                cache_key,
                CachedUsers(items=users),
                self.settings.glitchtip.users_cache_ttl,
            )
            return users

    def invite_user(self, org_slug: str, email: str, role: str) -> User:
        """Invite a user and clear organization users cache."""
        user = self.glitchtip_api.invite_user(org_slug, email, role)
        self._clear_cache(self._cache_key_org_users(org_slug))
        return user

    def delete_user(self, org_slug: str, pk: int) -> None:
        """Delete a user and clear organization users cache."""
        self.glitchtip_api.delete_user(org_slug, pk)
        self._clear_cache(self._cache_key_org_users(org_slug))

    def update_user_role(self, org_slug: str, pk: int, role: str) -> User:
        """Update user role and clear organization users cache."""
        user = self.glitchtip_api.update_user_role(org_slug, pk, role)
        self._clear_cache(self._cache_key_org_users(org_slug))
        return user

    # --- Team users ---

    def get_team_users(self, org_slug: str, team_slug: str) -> list[User]:
        """Get team members (cached with distributed locking).

        Args:
            org_slug: Organization slug
            team_slug: Team slug

        Returns:
            List of User objects
        """
        cache_key = self._cache_key_team_users(org_slug, team_slug)

        if cached := self.cache.get_obj(cache_key, CachedUsers):
            return cached.items

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedUsers):
                return cached.items

            users = self.glitchtip_api.team_users(org_slug, team_slug)
            self.cache.set_obj(
                cache_key,
                CachedUsers(items=users),
                self.settings.glitchtip.users_cache_ttl,
            )
            return users

    def add_user_to_team(self, org_slug: str, team_slug: str, user_pk: int) -> None:
        """Add user to team and clear team users cache."""
        self.glitchtip_api.add_user_to_team(org_slug, team_slug, user_pk)
        self._clear_cache(self._cache_key_team_users(org_slug, team_slug))

    def remove_user_from_team(
        self, org_slug: str, team_slug: str, user_pk: int
    ) -> None:
        """Remove user from team and clear team users cache."""
        self.glitchtip_api.remove_user_from_team(org_slug, team_slug, user_pk)
        self._clear_cache(self._cache_key_team_users(org_slug, team_slug))

    # --- Projects (extended) ---

    def create_project(
        self,
        org_slug: str,
        team_slug: str,
        name: str,
        platform: str | None,
    ) -> Project:
        """Create a project and clear projects cache."""
        project = self.glitchtip_api.create_project(org_slug, team_slug, name, platform)
        self._clear_cache(self._cache_key_projects(org_slug))
        return project

    def update_project(
        self,
        org_slug: str,
        slug: str,
        name: str,
        platform: str | None,
        event_throttle_rate: int,
    ) -> Project:
        """Update a project and clear projects cache."""
        project = self.glitchtip_api.update_project(
            org_slug, slug, name, platform, event_throttle_rate
        )
        self._clear_cache(self._cache_key_projects(org_slug))
        return project

    def delete_project(self, org_slug: str, slug: str) -> None:
        """Delete a project and clear projects cache."""
        self.glitchtip_api.delete_project(org_slug, slug)
        self._clear_cache(self._cache_key_projects(org_slug))

    def add_project_to_team(
        self, org_slug: str, project_slug: str, team_slug: str
    ) -> Project:
        """Add project to team and clear projects cache."""
        project = self.glitchtip_api.add_project_to_team(
            org_slug, project_slug, team_slug
        )
        self._clear_cache(self._cache_key_projects(org_slug))
        return project

    def remove_project_from_team(
        self, org_slug: str, project_slug: str, team_slug: str
    ) -> None:
        """Remove project from team and clear projects cache."""
        self.glitchtip_api.remove_project_from_team(org_slug, project_slug, team_slug)
        self._clear_cache(self._cache_key_projects(org_slug))
