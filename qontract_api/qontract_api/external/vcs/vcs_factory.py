"""Factory for creating VCS workspace clients with provider registry."""

from qontract_utils.vcs.provider_registry import get_default_registry

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.vcs.provider_factory import VCSProviderFactory
from qontract_api.external.vcs.vcs_workspace_client import VCSWorkspaceClient
from qontract_api.logger import get_logger
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


def create_vcs_workspace_client(
    repo_url: str,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> VCSWorkspaceClient:
    """Create VCSWorkspaceClient with provider registry pattern.

    Creates VCS workspace client using provider registry for extensible
    provider support. Automatically detects repository type (GitHub/GitLab)
    from URL and creates appropriate API client with:
    - Provider-specific configuration
    - Token retrieval from vault
    - Rate limiting
    - Caching with TTL for repository OWNERS data
    - Distributed locking for thread-safe cache updates

    Args:
        repo_url: Repository URL (e.g., https://github.com/owner/repo)
        cache: Cache backend for distributed cache and rate limit state
        settings: Application settings with VCS configuration

    Returns:
        VCSWorkspaceClient instance with full caching layer

    Example:
        >>> client = create_vcs_workspace_client(
        ...     "https://github.com/owner/repo",
        ...     cache,
        ...     settings,
        ... )
        >>> owners = client.get_owners(path="/", ref="main")
    """
    # Create provider registry with default providers (GitHub, GitLab)
    registry = get_default_registry()

    # Create provider factory with dependency injection
    provider_factory = VCSProviderFactory(
        registry=registry,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    # Create workspace client with provider factory
    return VCSWorkspaceClient(
        repo_url=repo_url,
        provider_factory=provider_factory,
        cache=cache,
        settings=settings,
    )
