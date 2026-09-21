"""Factory for creating GitlabWorkspaceClient instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.gitlab_api import GitlabApi

from qontract_api.gitlab.gitlab_workspace_client import GitlabWorkspaceClient

if TYPE_CHECKING:
    from qontract_utils.secret_reader import Secret

    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.secret_manager import SecretManager


def create_gitlab_workspace_client(
    secret: Secret,
    url: str,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
    *,
    ssl_verify: bool = True,
) -> GitlabWorkspaceClient:
    """Create a GitlabWorkspaceClient with credentials resolved from the secret backend.

    Args:
        secret: Secret reference for the GitLab instance token
        url: GitLab instance URL
        cache: Cache backend for distributed caching and locking
        secret_manager: Secret backend for resolving the token
        settings: Application settings
        ssl_verify: Whether to verify SSL certificates for this instance

    Returns:
        GitlabWorkspaceClient instance with caching layer
    """
    token = secret_manager.read(secret)

    gitlab_api = GitlabApi(
        url=url,
        token=token,
        ssl_verify=ssl_verify,
        timeout=settings.gitlab_projects.api_timeout,
    )

    return GitlabWorkspaceClient(
        gitlab_api=gitlab_api,
        url=url,
        cache=cache,
        settings=settings,
        token=token,
    )
