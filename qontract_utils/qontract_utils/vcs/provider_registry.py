"""VCS provider registry for managing multiple VCS providers.

Implements registry pattern for extensible VCS provider support.
"""

from qontract_utils.vcs.models import Provider
from qontract_utils.vcs.provider_protocol import VCSProviderProtocol
from qontract_utils.vcs.providers import GitHubProvider, GitLabProvider


class VCSProviderRegistry:
    """Registry for VCS providers.

    Manages VCS providers (GitHub, GitLab, etc.) and provides
    provider detection and lookup capabilities.

    Example:
        >>> registry = VCSProviderRegistry()
        >>> registry.register(GitHubProvider())
        >>> registry.register(GitLabProvider())
        >>> provider = registry.detect_provider("https://github.com/owner/repo")
        >>> provider.type
        Provider.GITHUB
    """

    def __init__(self) -> None:
        """Initialize empty provider registry."""
        self._providers: dict[Provider, VCSProviderProtocol] = {}

    def register(self, provider: VCSProviderProtocol) -> None:
        """Register a VCS provider.

        Args:
            provider: VCS provider instance implementing VCSProviderProtocol

        Raises:
            ValueError: If provider with same name already registered
        """
        if provider.type in self._providers:
            msg = f"Provider already registered: {provider.type.value}"
            raise ValueError(msg)

        self._providers[provider.type] = provider

    def detect_provider(self, url: str) -> VCSProviderProtocol:
        """Auto-detect VCS provider from repository URL.

        Iterates through registered providers and returns the first
        provider that can handle the URL.

        Args:
            url: Repository URL

        Returns:
            VCS provider that can handle the URL

        Raises:
            ValueError: If no provider can handle the URL

        Example:
            >>> registry = get_default_registry()
            >>> provider = registry.detect_provider("https://github.com/owner/repo")
            >>> provider.name
            'github'
        """
        for provider in self._providers.values():
            if provider.detect(url):
                return provider

        msg = f"No VCS provider found for URL: {url}"
        raise ValueError(msg)

    def get_provider(self, provider_type: Provider) -> VCSProviderProtocol:
        """Get VCS provider by name.

        Args:
            name: Provider name (e.g., "github", "gitlab")

        Returns:
            VCS provider instance

        Raises:
            ValueError: If provider not found

        Example:
            >>> registry = get_default_registry()
            >>> provider = registry.get_provider("github")
            >>> provider.name
            'github'
        """
        if provider_type not in self._providers:
            msg = f"Provider not found: {provider_type.value}"
            raise ValueError(msg)

        return self._providers[provider_type]

    def list_providers(self) -> list[Provider]:
        """List all registered provider names.

        Returns:
            List of provider names

        Example:
            >>> registry = get_default_registry()
            >>> registry.list_providers()
            [Provider.GITHUB, Provider.GITLAB]
        """
        return list(self._providers.keys())


def get_default_registry() -> VCSProviderRegistry:
    """Create VCS provider registry with default providers.

    Registers GitHub and GitLab providers by default.

    Returns:
        VCSProviderRegistry with GitHub and GitLab registered

    Example:
        >>> registry = get_default_registry()
        >>> registry.list_providers()
        ['github', 'gitlab']
    """
    registry = VCSProviderRegistry()
    registry.register(GitHubProvider())
    registry.register(GitLabProvider())
    return registry
