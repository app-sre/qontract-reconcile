"""VCS external API endpoints for repository OWNERS files."""

from qontract_api.external.vcs.models import RepoOwnersResponse, VCSProvider
from qontract_api.external.vcs.vcs_factory import create_vcs_workspace_client

__all__ = [
    "RepoOwnersResponse",
    "VCSProvider",
    "create_vcs_workspace_client",
]
