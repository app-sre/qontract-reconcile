"""GitlabWorkspaceClient: Caching layer for GitLab group/project data.

Layer 2 (Cache + Compute) following ADR-014.

Scoped to a single GitLab instance (one token, many groups)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import BaseModel
from qontract_utils.gitlab_api import GitlabApi, GitlabGroup, GitlabProject

from qontract_api.logger import get_logger

if TYPE_CHECKING:
    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)


class CachedGroup(BaseModel, frozen=True):
    """Serializable wrapper for a GitlabGroup's cacheable fields."""

    id: int
    project_names: list[str]


class GitlabWorkspaceClient:
    """Layer 2 for GitLab group/project administration."""

    def __init__(
        self,
        gitlab_api: GitlabApi,
        url: str,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        self.gitlab_api = gitlab_api
        self._url = url.rstrip("/")
        self.cache = cache
        self.settings = settings

    def _cache_key_group(self, group_name: str) -> str:
        return f"gitlab:{self._url}:group:{group_name}:projects"

    # ------------------------------------------------------------------
    # Cached read
    # ------------------------------------------------------------------

    def get_group(self, group_name: str) -> GitlabGroup:
        """Fetch a group and its project names (cached).

        Returns:
            GitlabGroup with id, full_path and project_names
        """
        cache_key = self._cache_key_group(group_name)

        if cached := self.cache.get_obj(cache_key, CachedGroup):
            return GitlabGroup(
                id=cached.id, full_path=group_name, project_names=cached.project_names
            )

        with self.cache.lock(cache_key):
            if cached := self.cache.get_obj(cache_key, CachedGroup):
                return GitlabGroup(
                    id=cached.id,
                    full_path=group_name,
                    project_names=cached.project_names,
                )

            group = self.gitlab_api.get_group(group_name)
            self.cache.set_obj(
                cache_key,
                CachedGroup(id=group.id, project_names=group.project_names),
                self.settings.gitlab_projects.group_projects_cache_ttl,
            )
            return group

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create_project(
        self, group_name: str, group_id: int, name: str
    ) -> GitlabProject:
        """Create a project under the group and invalidate its cached project list."""
        cache_key = self._cache_key_group(group_name)
        with self.cache.lock(cache_key):
            try:
                project = self.gitlab_api.create_project(group_id, name)
            finally:
                self.cache.delete(cache_key)
            return project

    def initiate_saas_bundle_repo(self, project_id: int) -> None:
        """Bootstrap a project as a SaaS bundle repo."""
        self.gitlab_api.initiate_saas_bundle_repo(project_id)

    def close(self) -> None:
        self.gitlab_api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
