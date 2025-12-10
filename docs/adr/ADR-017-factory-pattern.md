# ADR-017: Factory Pattern

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

Modern applications integrate with multiple external service providers that offer similar functionality through different APIs. Examples include:

- **VCS platforms**: GitHub, GitLab, Gitea, Bitbucket (repository data, OWNERS files)
- **Secret managers**: Vault, AWS Secrets Manager, Azure Key Vault, GCP Secret Manager
- **Cloud providers**: AWS, Azure, GCP, OpenStack (compute, storage, networking)
- **Messaging platforms**: Slack, Microsoft Teams, Discord, Mattermost
- **Ticketing systems**: Jira, GitHub Issues, GitLab Issues, ServiceNow

Each provider has:

- Different API endpoints and authentication mechanisms
- Provider-specific URL formats and conventions
- Different configuration requirements
- Different rate limiting characteristics
- Provider-specific feature sets

### Problem

Without a structured pattern, applications typically handle multiple providers using:

1. **Static if/elif chains**: Hardcoded provider detection and branching
2. **Duplicate configuration**: No clear structure for provider-specific settings
3. **Hidden dependencies**: Tight coupling between business logic and provider details
4. **Poor extensibility**: Adding new providers requires modifying core code

### Requirements

1. **Extensibility**: Support multiple providers without modifying core code when adding new providers
2. **Provider-Specific Configuration**: Each provider needs its own settings namespace (API URLs, tokens, rate limits)
3. **Auto-Detection**: Automatically detect provider from context (URL, identifier, etc.)
4. **Dependency Injection**: Follow ADR-011 - all dependencies must be injected, no hidden dependencies
5. **Provider Isolation**: Each provider handles its own detection logic, parsing, and client creation
6. **Testability**: Easy to test providers individually and mock provider behavior

## Decision

Implement **Factory Pattern** for managing external service providers with complete dependency injection.

The pattern separates concerns into distinct components:

1. **Provider Protocol**: Defines interface all providers must implement
2. **Factory**: Centralized registry managing provider instances
3. **Provider Implementations**: Self-contained provider classes (GitHub, Vault, AWS, etc.)
4. **Provider Factory**: Creates clients with provider-specific configuration and rate limiting
5. **Client Layer**: Provider-agnostic client using dependency injection

### Why Factory Pattern?

The Factory Pattern solves the fundamental problem of **extensibility with dependency injection**:

- **Registry as Service Locator**: Providers register themselves, core code doesn't need to know about them
- **Auto-Detection**: Registry iterates providers to find matching one based on context
- **Configuration Namespacing**: Each provider has isolated settings under `providers.<name>.*`
- **Factory Integration**: Factory uses registry to create properly configured clients
- **No Static Branches**: No `if provider == "github"` checks in core code
- **Protocol-Based**: Type-safe contracts without inheritance

### Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Router/Service (FastAPI/Business Logic)           │
│   Uses provider-agnostic client interface                  │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│ Layer 2: Workspace Client (caching + factory)              │
│                                                             │
│   ┌────────────────────────────────────────────┐            │
│   │ ProviderFactory                            │            │
│   │  ├─ Detect/lookup provider via registry    │            │
│   │  ├─ Get credentials from credential map    │            │
│   │  ├─ Get provider-specific settings         │            │
│   │  ├─ Create rate limiting hooks             │            │
│   │  └─ Provider creates API client            │            │
│   └────────────────────────────────────────────┘            │
│                                                             │
│   ┌────────────────────────────────────────────┐            │
│   │ ProviderRegistry                           │            │
│   │  ├─ register(provider)                     │            │
│   │  ├─ detect_provider(context) → provider    │            │
│   │  └─ get_provider(name) → provider          │            │
│   └────────────────────────────────────────────┘            │
│         │                                                   │
│         ├─ Provider A (detect, parse, create_client)        │
│         ├─ Provider B (detect, parse, create_client)        │
│         └─ Provider C (detect, parse, create_client)        │
│                                                             │
│   Client(api_client, provider_name, config)                │
│     └─ Provider-agnostic business operations               │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│ Layer 1: API Client Implementations                         │
│   ├─ Provider A Client (implements ProviderProtocol)        │
│   ├─ Provider B Client (implements ProviderProtocol)        │
│   └─ Provider C Client (implements ProviderProtocol)        │
└─────────────────────────────────────────────────────────────┘
```

### Generic Pattern Components

#### 1. Provider Protocol

Defines the contract all providers must implement:

```python
from typing import Protocol, Any
from collections.abc import Callable

class ProviderProtocol(Protocol):
    """Protocol that all providers must implement."""

    name: str  # Provider identifier: "github", "vault-aws", "slack", etc.

    def detect(self, context: str) -> bool:
        """Check if this provider can handle the given context.

        Args:
            context: Provider-specific context (URL, identifier, etc.)

        Returns:
            True if this provider handles the context

        Example VCS:
            context = "https://github.com/org/repo"
            return "github" in urlparse(context).hostname

        Example Secret Manager:
            context = "aws"  # or "vault" or "azure-keyvault"
            return context == self.name
        """
        ...

    def parse_context(self, context: str) -> dict[str, Any]:
        """Parse provider-specific context into structured data.

        Args:
            context: Provider-specific context

        Returns:
            Dict with provider-specific parsed data

        Example VCS:
            input: "https://github.com/owner/repo"
            output: {"owner": "owner", "repo": "repo"}

        Example Secret Manager:
            input: "secret/data/myapp/db-password"
            output: {"path": "secret/data/myapp/db-password"}
        """
        ...

    def create_client(
        self,
        context: str,
        credentials: Any,
        timeout: int,
        hooks: list[Callable] | None = None,
        provider_settings: Any,
    ) -> Any:
        """Create provider-specific client instance.

        Args:
            context: Provider-specific context (URL, path, etc.)
            credentials: Authentication credentials (token, API key, etc.)
            timeout: Request timeout in seconds
            hooks: Optional list of before-request hooks (rate limiting, logging)
            provider_settings: Provider-specific configuration options

        Returns:
            Configured provider client instance

        Example VCS:
            return GitHubRepoApi(
                owner=parsed["owner"],
                repo=parsed["repo"],
                token=credentials,
                github_api_url=provider_settings.api_url,
                timeout=timeout,
                before_api_call_hooks=hooks,
            )

        Example Secret Manager:
            return VaultClient(
                url=provider_settings.vault_url,
                token=credentials,
                timeout=timeout,
            )
        """
        ...
```

**Why Protocol?** Type-safe interface without inheritance. Providers don't need to subclass, just implement the protocol methods.

#### 2. Registry

Centralized registry for provider management:

```python
class ProviderRegistry[T: ProviderProtocol]:
    """Generic registry for managing providers.

    Type parameter T allows type-safe specialization:
    - VCSProviderRegistry = ProviderRegistry[VCSProviderProtocol]
    - SecretProviderRegistry = ProviderRegistry[SecretProviderProtocol]
    """

    def __init__(self) -> None:
        self._providers: dict[str, T] = {}

    def register(self, provider: T) -> None:
        """Register a provider.

        Args:
            provider: Provider instance implementing ProviderProtocol

        Raises:
            ValueError: If provider with same name already registered
        """
        if provider.name in self._providers:
            raise ValueError(f"Provider '{provider.name}' already registered")
        self._providers[provider.name] = provider

    def detect_provider(self, context: str) -> T:
        """Auto-detect provider from context.

        Args:
            context: Provider-specific context (URL, identifier, etc.)

        Returns:
            First provider that can handle the context

        Raises:
            ValueError: If no provider found for context
        """
        for provider in self._providers.values():
            if provider.detect(context):
                return provider
        raise ValueError(f"No provider found for context: {context}")

    def get_provider(self, name: str) -> T:
        """Get provider by name.

        Args:
            name: Provider name (e.g., "github", "vault", "aws")

        Returns:
            Provider instance

        Raises:
            KeyError: If provider not found
        """
        return self._providers[name]

    def list_providers(self) -> list[str]:
        """List all registered provider names."""
        return list(self._providers.keys())
```

**Why Registry?** Central place to manage providers, enables auto-detection, no hardcoded provider lists.

#### 3. Provider Implementations

Self-contained provider classes implementing the protocol:

```python
# Example: VCS Provider (GitHub)
class GitHubProvider:
    """GitHub VCS provider implementation."""

    name = "github"

    def detect(self, url: str) -> bool:
        """Detect GitHub URLs."""
        hostname = urlparse(url).hostname or ""
        return "github" in hostname.lower()

    def parse_context(self, url: str) -> dict[str, str]:
        """Parse GitHub URL to extract owner/repo."""
        # Parse: https://github.com/owner/repo → {"owner": "owner", "repo": "repo"}
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").removesuffix(".git")
        parts = [p for p in path.split("/") if p]

        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL format: {url}")

        return {"owner": parts[0], "repo": parts[1]}

    def create_client(self, url, token, timeout, hooks=None, provider_settings: GitHubProviderSettings):
        """Create GitHub API client."""
        parsed = self.parse_context(url)
        return GitHubRepoApi(
            owner=parsed["owner"],
            repo=parsed["repo"],
            token=token,
            github_api_url=provider_settings.api_url,
            timeout=timeout,
            before_api_call_hooks=hooks or [],
        )


# Example: Secret Manager Provider (Vault)
class VaultSecretProvider:
    """HashiCorp Vault secret provider implementation."""

    name = "vault"

    def detect(self, context: str) -> bool:
        """Detect Vault context (simple name match)."""
        return context == "vault"

    def parse_context(self, path: str) -> dict[str, str]:
        """Parse Vault secret path."""
        # secret/data/myapp/db-password → {"path": "secret/data/myapp/db-password"}
        return {"path": path}

    def create_client(self, path, token, timeout, hooks=None, provider_settings: VaultProviderSettings):
        """Create Vault client."""
        return VaultClient(
            url=provider_settings.vault_url,
            token=token,
            timeout=timeout,
            namespace=kwargs.get("namespace"),
        )
```

**Why Self-Contained?** Each provider owns its detection logic, parsing rules, and client creation. No dependencies on other providers.

#### 4. Factory

Creates clients with provider-specific configuration:

```python
class ProviderFactory[T: ProviderProtocol]:
    """Generic factory for creating provider clients with configuration."""

    def __init__(
        self,
        registry: ProviderRegistry[T],
        settings: Any,  # Application settings
        credential_providers: dict[str, Callable[[], Any]],
        cache: CacheBackend | None = None,
    ) -> None:
        """Initialize factory with injected dependencies (ADR-011).

        Args:
            registry: Provider registry for detection/lookup
            settings: Application settings with provider configurations
            credential_providers: Map of provider_name → credential fetcher
            cache: Optional cache backend for rate limiting/caching
        """
        self._registry = registry
        self._settings = settings
        self._credential_providers = credential_providers
        self._cache = cache

    def create_client(
        self,
        context: str,
        provider_name: str | None = None,
    ) -> tuple[Any, str]:
        """Create provider client with full configuration.

        Args:
            context: Provider-specific context (URL, path, identifier)
            provider_name: Optional provider name (auto-detect if None)

        Returns:
            Tuple of (configured_client, provider_name)

        Raises:
            ValueError: If provider not found or credentials missing
        """
        # 1. Get provider (auto-detect or explicit lookup)
        provider = (
            self._registry.get_provider(provider_name)
            if provider_name
            else self._registry.detect_provider(context)
        )

        # 2. Get credentials for this provider
        if provider.name not in self._credential_providers:
            raise ValueError(f"No credentials configured for provider: {provider.name}")
        credentials = self._credential_providers[provider.name]()

        # 3. Get provider-specific settings
        provider_config = self._get_provider_config(provider.name)

        # 4. Create rate limiting hooks (if cache available)
        hooks = []
        if self._cache:
            hooks.append(self._create_rate_limit_hook(provider.name, provider_config))

        # 5. Build provider-specific settings
        provider_settings = self._build_provider_settings(provider.name, provider_config)

        # 6. Provider creates client with all configuration
        client = provider.create_client(
            context=context,
            credentials=credentials,
            timeout=provider_settings.api_timeout,
            hooks=hooks,
            provider_settings=provider_settings,
        )

        return client, provider.name

    def _get_provider_config(self, provider_name: str) -> Any:
        """Get provider-specific settings from application config."""
        # Example: settings.vcs.providers.github
        #          settings.secrets.providers.vault
        ...

    def _create_rate_limit_hook(self, provider_name: str, settings: Any) -> Callable:
        """Create rate limiting hook for provider."""
        ...

    def _build_provider_settings(self, provider_name: str, settings: Any) -> GitHubProviderSettings | VaultProviderSettings | ...:
        """Build provider-specific settings."""
        ...
```

**Why Factory?** Centralized place for complex client creation with rate limiting, caching, and provider-specific configuration.

#### 5. Provider-Agnostic Client

Business logic client that uses injected provider client:

```python
class GenericClient:
    """Provider-agnostic client for business operations.

    This client doesn't know about provider details - it only knows
    the provider protocol interface.
    """

    def __init__(
        self,
        provider_client: Any,  # Provider-specific client
        provider_name: str,     # For logging/metrics
        config: Any | None = None,  # Additional configuration
    ) -> None:
        """Initialize with injected provider client (ADR-011).

        Args:
            provider_client: Provider-specific client instance
            provider_name: Provider name for logging/telemetry
            config: Optional additional configuration
        """
        self._client = provider_client
        self.provider_name = provider_name
        self.config = config

    def perform_operation(self, *args, **kwargs):
        """Business operation using provider client."""
        # Use self._client which implements provider protocol
        return self._client.some_method(*args, **kwargs)
```

**Why Pure DI?** No provider detection, no credential management, no configuration parsing. Single responsibility: business operations.

### Configuration Structure

Provider-specific settings with clear namespacing:

```python
from pydantic import BaseModel, Field

# Example: VCS Provider Settings
class GitHubProviderSettings(BaseModel):
    api_url: str = Field(default="https://api.github.com")
    api_timeout: int = Field(default=30)
    credential_path: str = Field(default="secret/github-token")
    rate_limit_tier: str = Field(default="tier2")
    rate_limit_tokens: int = Field(default=20)
    rate_limit_refill_rate: float = Field(default=1.0)

class GitLabProviderSettings(BaseModel):
    api_timeout: int = Field(default=30)
    credential_path: str = Field(default="secret/gitlab-token")
    rate_limit_tier: str = Field(default="tier2")

class VCSProvidersSettings(BaseModel):
    github: GitHubProviderSettings = Field(default_factory=GitHubProviderSettings)
    gitlab: GitLabProviderSettings = Field(default_factory=GitLabProviderSettings)

class VCSSettings(BaseModel):
    providers: VCSProvidersSettings = Field(default_factory=VCSProvidersSettings)
    cache_ttl: int = Field(default=300)


# Example: Secret Manager Provider Settings
class VaultProviderSettings(BaseModel):
    vault_url: str = Field(default="http://localhost:8200")
    api_timeout: int = Field(default=10)
    namespace: str | None = Field(default=None)

class AWSSecretsManagerSettings(BaseModel):
    region: str = Field(default="us-east-1")
    api_timeout: int = Field(default=10)

class SecretProvidersSettings(BaseModel):
    vault: VaultProviderSettings = Field(default_factory=VaultProviderSettings)
    aws: AWSSecretsManagerSettings = Field(default_factory=AWSSecretsManagerSettings)

class SecretsSettings(BaseModel):
    providers: SecretProvidersSettings = Field(default_factory=SecretProvidersSettings)
```

Environment variables follow the nested structure:

```bash
# VCS Provider Configuration
QAPI_VCS__PROVIDERS__GITHUB__API_URL=https://api.github.com
QAPI_VCS__PROVIDERS__GITHUB__API_TIMEOUT=30
QAPI_VCS__PROVIDERS__GITHUB__CREDENTIAL_PATH=secret/github-token
QAPI_VCS__PROVIDERS__GITHUB__RATE_LIMIT_TIER=tier2

QAPI_VCS__PROVIDERS__GITLAB__API_TIMEOUT=30
QAPI_VCS__PROVIDERS__GITLAB__CREDENTIAL_PATH=secret/gitlab-token
QAPI_VCS__PROVIDERS__GITLAB__RATE_LIMIT_TIER=tier3

# Secret Manager Provider Configuration
QAPI_SECRETS__PROVIDERS__VAULT__VAULT_URL=http://vault.example.com:8200
QAPI_SECRETS__PROVIDERS__VAULT__NAMESPACE=myapp

QAPI_SECRETS__PROVIDERS__AWS__REGION=us-west-2
```

**Why Nested Structure?** Each provider has isolated configuration namespace. Easy to add provider-specific options without conflicts.

## Use Cases

### Use Case 1: VCS Platforms (GitHub, GitLab, Gitea)

**Context**: Fetch OWNERS files from multiple VCS platforms

**Detection**: URL-based (`https://github.com/...`, `https://gitlab.com/...`)

**Provider-Specific**:

- URL parsing (owner/repo vs group/project)
- API endpoints (GitHub REST vs GitLab GraphQL)
- Authentication (tokens, OAuth apps)

**Benefits**:

- Add Bitbucket/Azure DevOps without changing core code
- Support enterprise/self-hosted instances easily
- Provider-specific rate limiting

### Use Case 2: Secret Managers (Vault, AWS, Azure, GCP)

**Context**: Read secrets from multiple secret management systems

**Detection**: Name-based or URL-based (`vault://...`, `aws-sm://...`)

**Provider-Specific**:

- API authentication methods
- Path structures (Vault KV vs AWS ARN)
- Encryption/decryption handling

**Benefits**:

- Switch secret backends without code changes
- Support multi-cloud deployments
- Provider-specific caching strategies

### Use Case 3: Cloud Providers (AWS, Azure, GCP)

**Context**: Manage cloud resources across multiple providers

**Detection**: Identifier-based or resource-based

**Provider-Specific**:

- Authentication (IAM roles, service principals)
- API clients (boto3, azure-sdk, google-cloud)
- Resource naming conventions

**Benefits**:

- Multi-cloud infrastructure management
- Provider-specific optimizations
- Easy testing with fake/local providers

### Use Case 4: Messaging Platforms (Slack, Teams, Discord)

**Context**: Send notifications to multiple messaging platforms

**Detection**: Webhook URL or platform identifier

**Provider-Specific**:

- Message formatting (Slack blocks vs Teams cards)
- Attachment handling
- Rate limiting

**Benefits**:

- Support multiple team communication tools
- Provider-specific rich formatting
- Gradual migration between platforms

## Alternatives Considered

### Alternative 1: Static Branches (Rejected)

Simple static branch functions without registry.

```python
def create_client(context: str, credentials: str):
    if "github" in context:
        return create_github_client(...)
    elif "gitlab" in context:
        return create_gitlab_client(...)
    # ... static if/elif chain
```

**Pros:**

- Simple, straightforward
- Less abstraction
- Easy to understand

**Cons:**

- Static if/elif branches - not extensible
- Adding provider requires modifying factory
- No provider-specific configuration namespacing
- Violates ADR-011 (hidden dependencies)
- Violates Open/Closed Principle

**Rejected:** Not extensible, doesn't scale.

### Alternative 2: Strategy Pattern (Rejected)

Provider selection with strategy interface.

```python
class ProviderStrategy(ABC):
    @abstractmethod
    def perform_operation(self, ...):
        ...

class Client:
    def __init__(self, strategy: ProviderStrategy):
        self._strategy = strategy
```

**Pros:**

- Well-known pattern
- Flexible provider selection
- Clean interface

**Cons:**

- Still need provider detection logic somewhere
- Doesn't solve configuration namespacing
- Doesn't address factory concerns
- More complex than needed

**Rejected:** Doesn't solve core problems.

### Alternative 3: Plugin System (Over-engineering)

Dynamic plugin loading with entry points.

**Pros:**

- Maximum extensibility
- Third-party provider packages
- Runtime discovery

**Cons:**

- Massive complexity
- Security concerns (code execution)
- Debugging difficulty
- Overkill for known provider set

**Rejected:** Over-engineered for requirements.

### Alternative 4: Factory Pattern (Selected)

**Pros:**

- **Extensible**: Add providers without modifying core code
- **Clean Separation**: Detection, parsing, creation, configuration isolated
- **Configuration Namespacing**: Each provider has `providers.<name>.*`
- **ADR-011 Compliant**: Complete dependency injection
- **Testable**: Mock registry, test providers individually
- **Auto-Detection**: Registry handles provider matching
- **Type-Safe**: Protocol-based with mypy checking
- **Scalable**: Works for 2 providers or 20 providers

**Cons:**

- More abstraction (Protocol, Registry, Factory)
- More initial code
- Learning curve

**Accepted:** Benefits outweigh costs, scales with system growth.

## Consequences

### Positive

1. **Extensibility**
   - Add new providers by creating provider class and registering
   - No modifications to core client, factory, or service code
   - Support enterprise/self-hosted instances easily

2. **Clean Architecture**
   - Single Responsibility: Each provider handles its detection and client creation
   - Dependency Injection: All dependencies explicit and injected (ADR-011)
   - Provider Isolation: Providers don't know about each other
   - Open/Closed Principle: Open for extension, closed for modification

3. **Configuration Clarity**
   - Provider-specific settings under `<domain>.providers.<name>.*`
   - Clear environment variable naming
   - Easy to add provider-specific options

4. **Better Testing**
   - Test providers individually without integration
   - Mock registry for unit tests
   - Test provider detection separately
   - Easy to test with fake providers

5. **Type Safety**
   - Protocol-based interfaces with mypy checking
   - No runtime type errors from wrong provider usage
   - IDE autocomplete for provider methods

6. **Reusability**
   - Same pattern works for VCS, secrets, cloud, messaging, etc.
   - Team learns pattern once, applies everywhere
   - Consistent architecture across integrations

### Negative

1. **More Abstraction**
   - Additional classes: Protocol, Registry, Factory, Providers
   - New developers need to understand pattern
   - **Mitigation**: Clear documentation, examples in ADR

2. **Initial Code Volume**
   - More files to create initially
   - More concepts to understand
   - **Mitigation**: Complexity pays off with extensibility

3. **Indirection**
   - Registry lookup adds layer
   - Not immediately obvious which provider handles context
   - **Mitigation**: Provider `detect()` methods are simple

## Implementation Guidelines

### Adding a New Provider (Step-by-Step)

Let's add Gitea VCS provider as example:

**Step 1: Create Provider Class**

```python
# qontract_utils/vcs/providers/gitea_provider.py
from urllib.parse import urlparse
from qontract_utils.vcs.provider_protocol import VCSProviderProtocol

class GiteaProvider:
    """Gitea VCS provider implementation."""

    name = "gitea"

    def detect(self, url: str) -> bool:
        """Detect Gitea URLs."""
        hostname = urlparse(url).hostname or ""
        return "gitea" in hostname.lower()

    def parse_context(self, url: str) -> dict[str, str]:
        """Parse Gitea URL."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").removesuffix(".git")
        parts = [p for p in path.split("/") if p]

        if len(parts) < 2:
            raise ValueError(f"Invalid Gitea URL: {url}")

        return {"owner": parts[0], "repo": parts[1]}

    def create_client(self, url, credentials, timeout, hooks=None, **kwargs):
        """Create Gitea API client."""
        parsed = self.parse_context(url)
        return GiteaRepoApi(
            owner=parsed["owner"],
            repo=parsed["repo"],
            token=credentials,
            gitea_api_url=kwargs.get("api_url", "https://gitea.com/api/v1"),
            timeout=timeout,
            before_api_call_hooks=hooks or [],
        )
```

**Step 2: Add Provider Settings**

```python
# config.py
class GiteaProviderSettings(BaseModel):
    api_url: str = Field(default="https://gitea.com/api/v1")
    api_timeout: int = Field(default=30)
    credential_path: str = Field(default="secret/gitea-token")
    rate_limit_tier: str = Field(default="tier2")

class VCSProvidersSettings(BaseModel):
    github: GitHubProviderSettings = Field(default_factory=GitHubProviderSettings)
    gitlab: GitLabProviderSettings = Field(default_factory=GitLabProviderSettings)
    gitea: GiteaProviderSettings = Field(default_factory=GiteaProviderSettings)  # Add
```

**Step 3: Register Provider**

```python
# factory.py
def create_vcs_client(...):
    registry = ProviderRegistry[VCSProviderProtocol]()
    registry.register(GitHubProvider())
    registry.register(GitLabProvider())
    registry.register(GiteaProvider())  # Add

    credential_providers = {
        "github": lambda: get_credential(settings.vcs.providers.github.credential_path),
        "gitlab": lambda: get_credential(settings.vcs.providers.gitlab.credential_path),
        "gitea": lambda: get_credential(settings.vcs.providers.gitea.credential_path),  # Add
    }

    factory = ProviderFactory(registry, settings, credential_providers, cache)
    ...
```

**Step 4: Update Factory kwargs Builder (if needed)**

```python
# factory.py
def _build_provider_kwargs(self, provider_name: str, settings: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}

    if provider_name == "github":
        kwargs["api_url"] = settings.api_url
    elif provider_name == "gitea":
        kwargs["api_url"] = settings.api_url  # Add

    return kwargs
```

**Done!** Core client, router, and business logic unchanged.

### Testing Providers

```python
def test_gitea_provider_detection():
    """Test Gitea URL detection."""
    provider = GiteaProvider()

    assert provider.detect("https://gitea.example.com/owner/repo")
    assert not provider.detect("https://github.com/owner/repo")

def test_gitea_provider_parsing():
    """Test Gitea URL parsing."""
    provider = GiteaProvider()

    parsed = provider.parse_context("https://gitea.example.com/myorg/myrepo")

    assert parsed["owner"] == "myorg"
    assert parsed["repo"] == "myrepo"

def test_provider_registry():
    """Test provider registry."""
    registry = ProviderRegistry[VCSProviderProtocol]()
    registry.register(GitHubProvider())
    registry.register(GiteaProvider())

    # Test detection
    github = registry.detect_provider("https://github.com/org/repo")
    assert github.name == "github"

    gitea = registry.detect_provider("https://gitea.example.com/org/repo")
    assert gitea.name == "gitea"

    # Test explicit lookup
    assert registry.get_provider("github").name == "github"
```

## References

**Related ADRs:**

- [ADR-011: Dependency Injection Pattern](ADR-011-dependency-injection-pattern.md)
- [ADR-014: Three-Layer Architecture for External APIs](ADR-014-three-layer-architecture-for-external-apis.md)

**Example Implementations:**

- **VCS Providers**: `qontract_utils/vcs/provider_*.py`
- **Secret Providers**: `qontract_utils/secret_reader/`
- **Registry**: `qontract_utils/*/*registry.py`
- **Factory**: `qontract_api/*/*factory.py`

**Pattern References:**

- [Registry Pattern - Martin Fowler](https://martinfowler.com/eaaCatalog/registry.html)
- [Dependency Injection - Martin Fowler](https://martinfowler.com/articles/injection.html)
- [Strategy Pattern - Gang of Four](https://en.wikipedia.org/wiki/Strategy_pattern)
- [Open/Closed Principle - SOLID](https://en.wikipedia.org/wiki/Open%E2%80%93closed_principle)

---

## Future Extensions

This pattern enables:

1. **Multiple Provider Types**
   - VCS: GitHub, GitLab, Gitea, Bitbucket, Azure DevOps
   - Secrets: Vault, AWS Secrets Manager, Azure Key Vault, GCP Secret Manager
   - Cloud: AWS, Azure, GCP, OpenStack, DigitalOcean
   - Messaging: Slack, Teams, Discord, Mattermost
   - Ticketing: Jira, GitHub Issues, GitLab Issues, ServiceNow

2. **Enterprise/Self-Hosted Support**
   - GitHub Enterprise with custom API URLs
   - Self-hosted GitLab/Gitea instances
   - Custom Vault deployments
   - On-premises cloud platforms

3. **Provider-Specific Features**
   - GitHub Apps authentication
   - Azure Managed Identity
   - GCP Workload Identity
   - Provider-specific optimizations
   - Custom rate limiting per instance

4. **Testing Improvements**
   - Fake providers for testing
   - Provider behavior mocking
   - Integration test isolation

The investment in proper abstraction prevents technical debt as the system scales to support more providers and deployment scenarios. The pattern is **provider-agnostic by design** - use it wherever you have multiple external service providers offering similar functionality.
