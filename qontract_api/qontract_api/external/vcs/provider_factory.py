"""Factory for creating VCS API clients with rate limiting and provider management."""

from qontract_utils.vcs import (
    GitHubProviderSettings,
    GitLabProviderSettings,
    VCSApiProtocol,
    VCSProviderProtocol,
    VCSProviderRegistry,
)
from qontract_utils.vcs.models import Provider

from qontract_api.cache import CacheBackend
from qontract_api.config import GitHubProviderSettings as GitHubProviderConfig
from qontract_api.config import GitLabProviderSettings as GitLabProviderConfig
from qontract_api.config import Settings


class VCSProviderFactory:
    """Factory for creating VCS API clients with rate limiting.

    Manages VCS providers and creates API clients with provider-specific
    configuration and rate limiting.
    """

    def __init__(
        self,
        token: str,
        registry: VCSProviderRegistry,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize VCS provider factory."""
        self._registry = registry
        self._cache = cache
        self._settings = settings
        self._token = token

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
        provider_type: Provider | None = None,
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
        if provider_type:
            provider = self._registry.get_provider(provider_type)
        else:
            provider = self._registry.detect_provider(url)

        provider_config: GitHubProviderConfig | GitLabProviderConfig = getattr(
            self._settings.vcs.providers, provider.type.value
        )

        api_client = provider.create_api_client(
            url=url,
            token=self._token,
            timeout=provider_config.api_timeout,
            hooks=[],
            provider_settings=self._build_provider_settings(provider_config),
        )

        return api_client, provider.type.value

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
