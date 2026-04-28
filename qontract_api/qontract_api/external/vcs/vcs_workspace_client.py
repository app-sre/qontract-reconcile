"""VCS Workspace Client with two-tier caching and distributed locking."""

from qontract_utils.vcs.models import RepoOwners
from qontract_utils.vcs.owners_parser import OwnersParser
from qontract_utils.vcs.provider_protocol import CreateMergeRequestInput

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

    Example:
        >>> factory = VCSProviderFactory(registry, cache, settings, token_providers)
        >>> client = VCSWorkspaceClient(
        ...     repo_url="https://github.com/owner/repo",
        ...     provider_factory=factory,
        ...     cache=cache,
        ...     settings=settings,
        ... )
        >>> owners = client.get_owners(owners_file="/OWNERS", ref="main")
    """

    def __init__(
        self,
        repo_url: str,
        provider_factory: VCSProviderFactory,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize VCS workspace client.

        Args:
            repo_url: Repository URL
            provider_factory: VCS provider factory (dependency injection)
            cache: Cache backend
            settings: Application settings
        """
        self.repo_url = repo_url
        self._cache = cache
        self._settings = settings

        # Provider factory creates API client with rate limiting
        self._api_client, provider_name = provider_factory.create_api_client(repo_url)

        self.provider_name = provider_name

    def get_owners(self, owners_file: str, ref: str) -> RepoOwners:
        """Get OWNERS data for repository path with caching.

        Implements two-tier caching with distributed locking:
        1. Check cache for existing data
        2. If cache miss: acquire lock, fetch from VCS API, update cache
        3. Return cached data

        Args:
            owners_file: Owners file path
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            RepoOwners with approvers and reviewers lists
        """
        # Cache key includes repo_url, path, and ref
        cache_key = f"vcs:owners:{self.repo_url}:{owners_file}:{ref}"

        # Try to get from cache first
        cached_owners = self._cache.get_obj(cache_key, RepoOwners)
        if cached_owners is not None:
            return cached_owners

        # Cache miss - acquire lock and fetch from API
        with self._cache.lock(cache_key, timeout=30):
            # Double-check cache after acquiring lock (another process may have updated it)
            cached_owners = self._cache.get_obj(cache_key, RepoOwners)
            if cached_owners is not None:
                return cached_owners

            # Fetch from VCS API
            owners = self._fetch_owners(owners_file, ref)

            # Update cache
            self._cache.set_obj(
                cache_key,
                owners,
                ttl=self._settings.vcs.owners_cache_ttl,
            )

            return owners

    def find_merge_request(self, title: str) -> str | None:
        """Find an open merge request by title.

        Args:
            title: MR title to search for (exact match)

        Returns:
            URL of the open merge request, or None if not found

        """
        return self._api_client.find_merge_request(title)

    def create_merge_request(self, mr_input: CreateMergeRequestInput) -> str:
        """Create a merge request with file changes.

        Delegates to the underlying VCS API client.

        Args:
            mr_input: Merge request details including file operations

        Returns:
            URL of the created merge request

        """
        return self._api_client.create_merge_request(mr_input)

    def get_file(self, path: str, ref: str) -> str | None:
        """Get file content from repository.

        Delegates to the underlying VCS API client (no caching).

        Args:
            path: File path relative to repository root
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            File content as string, or None if not found
        """
        return self._api_client.get_file(path, ref=ref)

    def _fetch_owners(self, owners_file: str, ref: str) -> RepoOwners:
        """Fetch OWNERS data from VCS API.

        Args:
            owners_file: Owners file path
            ref: Git reference (branch, tag, commit SHA)

        Returns:
            RepoOwners with approvers and reviewers
        """
        parser = OwnersParser(vcs_client=self._api_client, ref=ref)
        return parser.get_owners(owners_file)
