"""VCS (Version Control System) API clients for GitHub and GitLab.

Provides a unified interface for interacting with Git repositories across
different platforms (GitHub, GitLab) to fetch OWNERS files and repository data.

Following ADR-011: Dependency Injection Pattern
Following ADR-014: Three-Layer Architecture (Layer 1)
Following ADR-017: VCS Provider Registry Pattern
"""

from qontract_utils.vcs.models import OwnersFileData, RepoOwners, RepoTreeItem
from qontract_utils.vcs.owners_parser import OwnersParser
from qontract_utils.vcs.provider_protocol import VCSApiProtocol, VCSProviderProtocol
from qontract_utils.vcs.provider_registry import (
    VCSProviderRegistry,
    get_default_registry,
)
from qontract_utils.vcs.providers.github_client import GitHubRepoApi
from qontract_utils.vcs.providers.github_provider import (
    GitHubProvider,
    GitHubProviderSettings,
)
from qontract_utils.vcs.providers.gitlab_client import GitLabRepoApi
from qontract_utils.vcs.providers.gitlab_provider import (
    GitLabProvider,
    GitLabProviderSettings,
)
from qontract_utils.vcs.vcs_client import VCSClient

__all__ = [
    "GitHubProvider",
    "GitHubProviderSettings",
    "GitHubRepoApi",
    "GitLabProvider",
    "GitLabProviderSettings",
    "GitLabRepoApi",
    "OwnersFileData",
    "OwnersParser",
    "RepoOwners",
    "RepoTreeItem",
    "VCSApiProtocol",
    "VCSClient",
    "VCSProviderProtocol",
    "VCSProviderRegistry",
    "get_default_registry",
]
