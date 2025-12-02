"""VCS provider implementations for provider registry pattern.

Following ADR-017: VCS Provider Registry Pattern
"""

from qontract_utils.vcs.providers.github_provider import GitHubProvider
from qontract_utils.vcs.providers.gitlab_provider import GitLabProvider

__all__ = [
    "GitHubProvider",
    "GitLabProvider",
]
