"""VCS Workspace Client with two-tier caching and distributed locking."""

from qontract_utils.vcs.models import RepoOwners
from qontract_utils.vcs.owners_parser import OwnersParser
from qontract_utils.vcs.vcs_client import VCSClient

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.vcs.provider_factory import VCSProviderFactory


class VCSWorkspaceClient:
    """VCS Workspace Client with caching for OWNERS files.

    Provides two-tier caching (memory + Redis) with distributed locking for
    repository OWNERS data. Uses provider factory for extensible provider support.

    Args:
        repo_url: Repository URL (e.g., https://github.com/owner/repo)
        provider_factory: VCS provider factory for creating API clients
        cache: Cache backend for distributed cache
        settings: Application settings with VCS configuration
        ref: Git reference (branch, tag, commit SHA)

    Example:
        >>> factory = VCSProviderFactory(registry, cache, settings, token_providers)
        >>> client = VCSWorkspaceClient(
        ...     repo_url="https://github.com/owner/repo",
        ...     provider_factory=factory,
        ...     cache=cache,
        ...     settings=settings,
        ... )
        >>> owners = client.get_owners(path="/", ref="main")
    """

    def __init__(
        self,
        repo_url: str,
        provider_factory: VCSProviderFactory,
        cache: CacheBackend,
        settings: Settings,
        ref: str = "master",
    ) -> None:
        """Initialize VCS workspace client.

        Args:
            repo_url: Repository URL
            provider_factory: VCS provider factory (dependency injection)
            cache: Cache backend
            settings: Application settings
            ref: Git reference
        """
        self.repo_url = repo_url
        self._cache = cache
        self._settings = settings
        self._ref = ref

        # Provider factory creates API client with rate limiting
        self._api_client, provider_name = provider_factory.create_api_client(repo_url)

        # VCS client with dependency injection
        self._vcs_client = VCSClient(
            api_client=self._api_client,
            provider_name=provider_name,
            ref=ref,
        )

        self.provider_name = provider_name

    def get_owners(self, path: str, ref: str = "master") -> RepoOwners:
        """Get OWNERS data for repository path with caching.

        Implements two-tier caching with distributed locking:
        1. Check cache for existing data
        2. If cache miss: acquire lock, fetch from VCS API, update cache
        3. Return cached data

        Args:
            path: Repository path ("/" for root, "/src" for specific path, "ALL" for all)
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            RepoOwners with approvers and reviewers lists
        """
        # Cache key includes repo_url, path, and ref
        cache_key = f"vcs:owners:{self.repo_url}:{path}:{ref}"

        # Try to get from cache first
        cached_owners = self._cache.get_obj(cache_key, RepoOwners)
        if cached_owners is not None:
            return cached_owners

        # Cache miss - acquire lock and fetch from API
        lock_key = f"{cache_key}:lock"
        with self._cache.lock(lock_key, timeout=30):
            # Double-check cache after acquiring lock (another process may have updated it)
            cached_owners = self._cache.get_obj(cache_key, RepoOwners)
            if cached_owners is not None:
                return cached_owners

            # Fetch from VCS API
            owners = self._fetch_owners(path, ref)

            # Update cache
            self._cache.set_obj(
                cache_key,
                owners,
                ttl=self._settings.vcs.owners_cache_ttl,
            )

            return owners

    def _fetch_owners(self, path: str, ref: str) -> RepoOwners:
        """Fetch OWNERS data from VCS API.

        Args:
            path: Repository path ("/" for root, "/src" for specific path)
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            RepoOwners with approvers and reviewers
        """
        parser = OwnersParser(vcs_client=self._api_client, ref=ref)
        return parser.get_owners(path)
