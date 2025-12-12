"""Factory for creating VCS API clients with rate limiting and provider management."""

from collections.abc import Callable
from typing import Any

from qontract_utils.vcs import (
    GitHubProvider,
    GitHubProviderSettings,
    GitLabProvider,
    GitLabProviderSettings,
    VCSApiProtocol,
    VCSProviderProtocol,
    VCSProviderRegistry,
)

from qontract_api.cache import CacheBackend
from qontract_api.config import GitHubProviderSettings as GitHubProviderConfig
from qontract_api.config import GitLabProviderSettings as GitLabProviderConfig
from qontract_api.config import Settings
from qontract_api.rate_limit.token_bucket import TokenBucket
from qontract_api.secret_manager import SecretManager


class VCSProviderFactory:
    """Factory for creating VCS API clients with rate limiting.

    Manages VCS providers and creates API clients with provider-specific
    configuration and rate limiting.
    """

    def __init__(
        self,
        registry: VCSProviderRegistry,
        cache: CacheBackend,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        """Initialize VCS provider factory."""
        self._registry = registry
        self._cache = cache
        self._settings = settings
        self._secret_manager = secret_manager

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
        if provider_name:
            provider = self._registry.get_provider(provider_name)
        else:
            provider = self._registry.detect_provider(url)

        provider_config: GitHubProviderConfig | GitLabProviderConfig = getattr(
            self._settings.vcs.providers, provider.name
        )

        match provider_config:
            case GitHubProviderConfig():
                gh_repo = GitHubProvider.parse_url(url)
                org_url = gh_repo.owner_url
                if org_url not in provider_config.organizations:
                    if "default" not in provider_config.organizations:
                        raise ValueError(
                            f"No token provider configured for organization: {gh_repo.owner}"
                        )
                    org_url = "default"
                token = self._secret_manager.read(
                    provider_config.organizations[org_url].token
                )
            case GitLabProviderConfig():
                gl_repo = GitLabProvider.parse_url(url)
                gl_url = gl_repo.gitlab_url
                if gl_url not in provider_config.instances:
                    if "default" not in provider_config.instances:
                        raise ValueError(
                            f"No token provider configured for GitLab instance: {gl_url}"
                        )
                    gl_url = "default"
                token = self._secret_manager.read(
                    provider_config.instances[gl_url].token
                )
            case _:
                raise ValueError(f"No token provider configured for: {provider.name}")

        rate_limit_hook = self._create_rate_limit_hook(
            provider_name=provider.name,
            url=url,
            provider_settings=provider_config,
        )

        api_client = provider.create_api_client(
            url=url,
            token=token,
            timeout=provider_config.api_timeout,
            hooks=[rate_limit_hook],
            provider_settings=self._build_provider_settings(provider_config),
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
    def _build_provider_settings(
        provider_config: GitHubProviderConfig | GitLabProviderConfig,
    ) -> GitHubProviderSettings | GitLabProviderSettings:
        """Build provider-specific settings."""
        match provider_config:
            case GitHubProviderConfig():
                return GitHubProviderSettings(
                    github_api_url=provider_config.api_url,
                )
            case GitLabProviderConfig():
                return GitLabProviderSettings()
            case _:
                raise ValueError(f"Unsupported provider config: {provider_config}")
