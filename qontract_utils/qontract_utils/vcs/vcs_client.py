"""VCS client abstraction for repository operations.

Provides unified interface for working with Git repositories across platforms.
"""

from qontract_utils.vcs.models import RepoOwners
from qontract_utils.vcs.owners_parser import OwnersParser
from qontract_utils.vcs.provider_protocol import VCSApiProtocol


class VCSClient:
    """Unified VCS client for repository operations.

    Provides platform-agnostic interface for repository operations.
    Uses dependency injection for VCS API client (GitHub, GitLab, etc.).

    Args:
        api_client: VCS API client implementing VCSApiProtocol
        provider_name: Provider name (e.g., "github", "gitlab")
        ref: Git reference (branch, tag, commit SHA)

    Example:
        >>> # Create via provider factory (recommended)
        >>> provider = GitHubProvider()
        >>> api_client = provider.create_api_client(...)
        >>> client = VCSClient(
        ...     api_client=api_client,
        ...     provider_name=provider.name,
        ...     ref="main",
        ... )
        >>> owners = client.get_owners()
    """

    def __init__(
        self,
        api_client: VCSApiProtocol,
        provider_name: str,
        ref: str = "master",
    ) -> None:
        """Initialize VCS client with dependency injection.

        Args:
            api_client: VCS API client (GitHubRepoApi, GitLabRepoApi, etc.)
            provider_name: Provider name for identification
            ref: Git reference (branch, tag, commit SHA)
        """
        self._api_client = api_client
        self.provider_name = provider_name
        self.ref = ref
        self._owners_parser = OwnersParser(vcs_client=api_client, ref=ref)

    def get_owners(self, path: str = "/") -> RepoOwners:
        """Get owners for specific path (including inherited owners).

        Args:
            path: Repository path (e.g., "/src/api")

        Returns:
            RepoOwners with accumulated approvers and reviewers
        """
        return self._owners_parser.get_owners(path)
