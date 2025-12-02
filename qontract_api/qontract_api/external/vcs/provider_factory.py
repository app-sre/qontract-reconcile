"""Factory for creating VCS API clients with rate limiting and provider management."""

from collections.abc import Callable
from typing import Any

from qontract_utils.secret_reader import SecretBackend
from qontract_utils.vcs import (
    GitHubProvider,
    GitLabProvider,
    VCSApiProtocol,
    VCSProviderProtocol,
    VCSProviderRegistry,
)

from qontract_api.cache import CacheBackend
from qontract_api.config import GitHubProviderSettings, GitLabProviderSettings, Settings
from qontract_api.rate_limit.token_bucket import TokenBucket


class VCSProviderFactory:
    """Factory for creating VCS API clients with rate limiting.

    Manages VCS providers and creates API clients with provider-specific
    configuration and rate limiting.

    Args:
        registry: VCS provider registry with registered providers
        cache: Cache backend for distributed rate limit state
        settings: Application settings with VCS configuration
        token_providers: Dict mapping provider name to token retrieval function
            Example: {"github": get_github_token_fn, "gitlab": get_gitlab_token_fn}

    Example:
        >>> registry = get_default_registry()
        >>> token_providers = {
        ...     "github": lambda: get_token_from_vault("secret/github"),
        ...     "gitlab": lambda: get_token_from_vault("secret/gitlab"),
        ... }
        >>> factory = VCSProviderFactory(registry, cache, settings, token_providers)
        >>> api_client, provider_name = factory.create_api_client(
        ...     "https://github.com/owner/repo"
        ... )
    """

    def __init__(
        self,
        registry: VCSProviderRegistry,
        cache: CacheBackend,
        secret_reader: SecretBackend,
        settings: Settings,
    ) -> None:
        """Initialize VCS provider factory.

        Args:
            registry: VCS provider registry
            cache: Cache backend for rate limiting
            settings: Application settings
            token_providers: Provider name to token function mapping
        """
        self._registry = registry
        self._cache = cache
        self._settings = settings
        self._secret_reader = secret_reader

    def detect_provider(self, url: str) -> VCSProviderProtocol:
        """Detect VCS provider from repository URL.

        Args:
            url: Repository URL

        Returns:
            VCS provider that can handle the URL

        Raises:
            ValueError: If no provider found for URL
        """
        return self._registry.detect_provider(url)

    def create_api_client(
        self,
        url: str,
        provider_name: str | None = None,
    ) -> tuple[VCSApiProtocol, str]:
        """Create VCS API client with rate limiting.

        Creates API client using provider-specific configuration:
        - Token from token provider function
        - Timeout from provider settings
        - Rate limiter hook from provider settings
        - Provider-specific kwargs (e.g., github_api_url)

        Args:
            url: Repository URL
            provider_name: Optional provider name. If None, auto-detect from URL.

        Returns:
            Tuple of (api_client, provider_name)

        Raises:
            ValueError: If provider not found or no token provider configured

        Example:
            >>> api_client, name = factory.create_api_client(
            ...     "https://github.com/owner/repo"
            ... )
            >>> name
            'github'
        """
        # 1. Get provider (detect or lookup by name)
        if provider_name:
            provider = self._registry.get_provider(provider_name)
        else:
            provider = self._registry.detect_provider(url)

        # 3. Get provider settings
        provider_settings: GitHubProviderSettings | GitLabProviderSettings = getattr(
            self._settings.vcs.providers, provider.name
        )

        match provider_settings:
            case GitHubProviderSettings():
                gh_repo = GitHubProvider.parse_url(url)
                org_url = gh_repo.owner_url
                if org_url not in provider_settings.organisations:
                    if "default" not in provider_settings.organisations:
                        raise ValueError(
                            f"No token provider configured for organisation: {gh_repo.owner}"
                        )
                    org_url = "default"
                token = self._secret_reader.read(
                    provider_settings.organisations[org_url].token
                )
            case GitLabProviderSettings():
                gl_repo = GitLabProvider.parse_url(url)
                gl_url = gl_repo.gitlab_url
                if gl_url not in provider_settings.instances:
                    if "default" not in provider_settings.instances:
                        raise ValueError(
                            f"No token provider configured for GitLab instance: {gl_url}"
                        )
                    gl_url = "default"
                token = self._secret_reader.read(
                    provider_settings.instances[gl_url].token
                )
            case _:
                raise ValueError(f"No token provider configured for: {provider.name}")

        # 4. Create rate limiter hook
        rate_limit_hook = self._create_rate_limit_hook(
            provider_name=provider.name,
            url=url,
            provider_settings=provider_settings,
        )

        # 5. Build provider-specific kwargs
        kwargs = self._build_provider_kwargs(provider.name, provider_settings)

        # 6. Provider creates API client
        api_client = provider.create_api_client(
            url=url,
            token=token,
            timeout=provider_settings.api_timeout,
            hooks=[rate_limit_hook],
            **kwargs,
        )

        return api_client, provider.name

    def _create_rate_limit_hook(
        self,
        provider_name: str,
        url: str,
        provider_settings: Any,
    ) -> Callable[[Any], None]:
        """Create rate limiting hook for provider.

        Args:
            provider_name: Provider name (e.g., "github")
            url: Repository URL (for bucket naming)
            provider_settings: Provider-specific settings with rate limit config

        Returns:
            Hook function that acquires token before API call
        """
        # Create token bucket with provider-specific settings
        bucket_name = f"{provider_name}:{provider_settings.rate_limit_tier}:{url}"
        token_bucket = TokenBucket(
            cache=self._cache,
            bucket_name=bucket_name,
            capacity=provider_settings.rate_limit_tokens,
            refill_rate=provider_settings.rate_limit_refill_rate,
        )

        def rate_limit_hook(_context: Any) -> None:
            """Rate limiting hook - acquires token before API call."""
            token_bucket.acquire(tokens=1, timeout=30)

        return rate_limit_hook

    @staticmethod
    def _build_provider_kwargs(
        provider_name: str,
        provider_settings: Any,
    ) -> dict[str, Any]:
        """Build provider-specific keyword arguments.

        Args:
            provider_name: Provider name (e.g., "github", "gitlab")
            provider_settings: Provider-specific settings

        Returns:
            Dict of provider-specific kwargs

        Example:
            >>> kwargs = factory._build_provider_kwargs("github", github_settings)
            >>> kwargs
            {"github_api_url": "https://api.github.com"}
        """
        kwargs: dict[str, Any] = {}

        # GitHub-specific kwargs
        if provider_name == "github":
            kwargs["github_api_url"] = provider_settings.api_url

        # GitLab doesn't need extra kwargs (gitlab_url extracted from URL by provider)
        return kwargs
