# ADR-011: Dependency Injection Pattern

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

Services and business logic layers often need access to external resources like secrets, configuration, database connections, or external API clients. How these dependencies are provided affects testability, flexibility, and maintainability.

**Current Situation:**

- Services need external resources (secrets from Vault, configuration, API clients)
- Direct instantiation creates tight coupling to concrete implementations
- Hard to test services that directly access external systems
- Difficult to swap implementations (e.g., mock Vault in tests, use different secret storage)

**Problems with Direct Dependency Access:**

- **Tight coupling:** Service directly imports and uses concrete implementations
- **Hard to test:** Can't easily mock external systems (Vault, databases, APIs)
- **Inflexible:** Can't swap implementations without changing service code
- **Hidden dependencies:** Not clear what external resources a service needs
- **Violates SOLID:** Dependency Inversion Principle violated (depend on abstractions, not concretions)

**Requirements:**

- Services should be decoupled from concrete implementations
- Easy to test with mocked dependencies
- Clear declaration of what dependencies a service needs
- Caller controls how dependencies are resolved
- Type-safe dependency contracts
- Minimal boilerplate

**Constraints:**

- Must work with Python's type system (mypy)
- Should not require complex DI frameworks

## Decision

We adopt **constructor-based dependency injection** using concrete class instances typed with `Protocol` interfaces.

Services declare dependencies as constructor parameters with type hints. Callers provide concrete implementations. Dependencies are abstracted using Protocol types, allowing any implementation that satisfies the protocol contract.

### Key Points

- **Constructor injection:** Dependencies passed via `__init__` parameters as class instances
- **Protocol types:** Use `Protocol` for type hints (e.g., `SecretBackend`, `CacheBackend`)
- **Concrete classes:** Inject actual class instances, not functions
- **Caller responsibility:** Router/FastAPI provides concrete implementations via dependency injection
- **Type safety:** Full mypy type checking of dependency contracts via Protocol types

## Alternatives Considered

### Alternative 1: Direct Instantiation

Service directly creates and uses concrete implementations.

```python
class SlackService:
    def __init__(self, workspace: str):
        self.workspace = workspace
        # Direct instantiation - tight coupling!
        self.vault_client = VaultClient(url=VAULT_URL, token=VAULT_TOKEN)
        self.slack_api = SlackApi(token=self._get_token())

    def _get_token(self) -> str:
        # Direct Vault access
        return self.vault_client.read(f"slack/{self.workspace}/token")
```

**Pros:**

- Simple, no dependency injection needed
- Easy to understand (all dependencies visible in code)
- No additional abstraction layer

**Cons:**

- Tight coupling to VaultClient implementation
- Impossible to test without real Vault
- Can't swap Vault implementation (e.g., environment variables in dev)
- Hard to mock for unit tests
- Violates Dependency Inversion Principle
- Service knows too much about how to get secrets
- Requires monkey patching for testing. This is not a common concept in other languages which makes it harder to use for Python beginners.

### Alternative 2: Dependency Injection Framework

Use a full DI framework like `dependency-injector` or `injector`.

```python
from dependency_injector import containers, providers

class Container(containers.DeclarativeContainer):
    config = providers.Configuration()
    vault = providers.Singleton(VaultClient, ...)
    slack_service = providers.Factory(
        SlackService,
        get_secret=vault.provided.read
    )

# Usage
container = Container()
service = container.slack_service(workspace="app-sre")
```

**Pros:**

- Centralized dependency configuration
- Supports complex dependency graphs
- Lifetime management (singleton, transient)
- Popular in enterprise applications

**Cons:**

- Heavy dependency (large library)
- Learning curve (framework-specific concepts)
- Magic/implicit behavior (hard to debug)
- Overkill for simple use cases
- Additional complexity in testing
- Not needed for our simple dependency structure

### Alternative 3: Constructor-Based Dependency Injection (Selected)

Inject dependencies as concrete classes via constructor, using Protocol types for abstraction.

```python
from qontract_utils.secret_reader.base import SecretBackend

class SlackUsergroupsService:
    """Service for reconciling Slack usergroups.

    Uses Dependency Injection to keep service decoupled from implementation details.
    """

    def __init__(
        self,
        slack_client_factory: SlackClientFactory,
        secret_reader: SecretBackend,
        settings: Settings,
    ) -> None:
        """Initialize service.

        Args:
            slack_client_factory: Factory for creating SlackWorkspaceClient instances
            secret_reader: Secret backend for retrieving Slack tokens
            settings: Application settings
        """
        self.slack_client_factory = slack_client_factory
        self.secret_reader = secret_reader
        self.settings = settings

    def reconcile(self, workspaces: list[SlackWorkspace], dry_run: bool):
        """Reconcile Slack usergroups."""
        # Use secret_reader to get token (injected dependency)
        token = self.secret_reader.read(f"slack/{workspace}/token")

        # Use factory to create client (injected dependency)
        slack = self.slack_client_factory.create_workspace_client(
            workspace_name=workspace,
            token=token,
        )

        # Business logic...

# Router provides concrete implementations
from qontract_utils.secret_reader.vault import VaultSecretReader
from qontract_api.cache.redis import RedisCacheBackend

service = SlackUsergroupsService(
    slack_client_factory=SlackClientFactory(cache_backend=cache),
    secret_reader=VaultSecretReader(),
    settings=app_settings,
)
```

**Pros:**

- **Explicit dependencies** - Clear what service needs via constructor signature
- **Easy to test** - Inject mocks for unit testing
- **No framework dependency** - Uses standard Python patterns
- **Type-safe with mypy** - Full type checking via Protocol types
- **Caller controls implementation** - Router decides concrete implementations
- **Follows Dependency Inversion Principle** - Depend on abstractions (SecretBackend Protocol)
- **Class-based** - More Pythonic than Callable, better IDE support
- **Real-world example** - Matches production code patterns

**Cons:**

- **More constructor parameters** - Services have more `__init__` parameters
  - **Mitigation:** Only inject true external dependencies, not business data
  - **Mitigation:** Use factory functions to centralize dependency wiring
- **Manual wiring in router/factory**
  - **Mitigation:** Centralize in factory functions or use FastAPI dependency injection

## Consequences

### Positive

- **Testability:** Easy to mock dependencies in unit tests using `MagicMock(spec=Protocol)`
- **Flexibility:** Swap implementations without changing service code (e.g., VaultSecretReader → EnvSecretReader)
- **Explicit contracts:** Protocol types document dependency requirements clearly
- **Decoupling:** Service depends on abstractions (`SecretBackend`), not concrete implementations (`VaultSecretReader`)
- **Type safety:** mypy validates dependency types at compile time via Protocol types
- **SOLID compliance:** Follows Dependency Inversion Principle (depend on abstractions)
- **No framework lock-in:** Uses standard Python patterns (no external DI frameworks)
- **Better IDE support:** Class-based dependencies provide better autocomplete and go-to-definition

### Negative

- **More constructor parameters:** Services have more `__init__` parameters
  - **Mitigation:** Only inject external dependencies (secrets, clients), not business data
  - **Mitigation:** Use factory functions to centralize dependency wiring

- **Manual wiring:** Must wire dependencies in router/factory
  - **Mitigation:** Create factory functions for common patterns
  - **Mitigation:** FastAPI's `Depends()` can provide dependencies automatically

- **Learning curve:** Developers must understand DI pattern
  - **Mitigation:** Document pattern with examples
  - **Mitigation:** Use in all new services for consistency

## Implementation Guidelines

### Pattern 1: Class-Based Dependencies (Recommended)

For most dependencies, inject concrete class instances typed with Protocol:

```python
from qontract_utils.secret_reader.base import SecretBackend
from qontract_api.config import Settings

class SlackUsergroupsService:
    """Service for reconciling Slack usergroups.

    Uses Dependency Injection to keep service decoupled from implementation details.
    """

    def __init__(
        self,
        slack_client_factory: SlackClientFactory,
        secret_reader: SecretBackend,  # Protocol type - any implementation works
        settings: Settings,
    ) -> None:
        """Initialize service with dependencies.

        Args:
            slack_client_factory: Factory for creating SlackWorkspaceClient instances
            secret_reader: Secret backend for retrieving Slack tokens (Protocol)
            settings: Application settings
        """
        self.slack_client_factory = slack_client_factory
        self.secret_reader = secret_reader
        self.settings = settings

    def reconcile(self, workspaces: list[SlackWorkspace], dry_run: bool):
        """Business logic using injected dependencies."""
        # Use secret_reader (Protocol) - works with any implementation
        token = self.secret_reader.read(f"slack/{workspace}/token")

        # Use factory to create workspace client
        slack = self.slack_client_factory.create_workspace_client(
            workspace_name=workspace,
            token=token,
        )

        # Business logic...
```

**Why class-based?**

- Better IDE support (autocomplete, go-to-definition)
- More Pythonic than Callable functions
- Easier to understand dependency relationships
- Protocol types provide compile-time type checking
- Matches existing qontract-reconcile patterns

### Pattern 2: Complex Dependencies (Protocol)

For multi-method dependencies, use `typing.Protocol`:

```python
from typing import Protocol

class CacheBackend(Protocol):
    """Protocol for cache implementations."""

    def get(self, key: str) -> str | None:
        """Get value from cache."""
        ...

    def set(self, key: str, value: str, ttl: int) -> None:
        """Set value in cache with TTL."""
        ...

class MyService:
    """Service with protocol dependency."""

    def __init__(self, cache: CacheBackend):
        """Initialize with cache backend.

        Args:
            cache: Cache implementation (Redis, in-memory, etc.)
        """
        self.cache = cache

    def get_data(self, key: str) -> str | None:
        """Get data with caching."""
        if cached := self.cache.get(key):
            return cached

        data = self._fetch_from_api(key)
        self.cache.set(key, data, ttl=300)
        return data
```

### Pattern 3: FastAPI Dependency Injection

Use FastAPI's built-in dependency injection for automatic wiring:

```python
from fastapi import Depends
from qontract_utils.secret_reader.base import SecretBackend
from qontract_api.dependencies import (
    get_secret_reader,
    get_slack_client_factory,
    get_settings,
)

@router.post("/api/integrations/slack-usergroups/reconcile")
async def reconcile_slack_usergroups(
    request: SlackUsergroupsReconcileRequest,
    # FastAPI automatically injects dependencies
    slack_client_factory: SlackClientFactory = Depends(get_slack_client_factory),
    secret_reader: SecretBackend = Depends(get_secret_reader),
    settings: Settings = Depends(get_settings),
) -> SlackUsergroupsTaskResponse:
    """Reconcile Slack usergroups endpoint.

    FastAPI automatically provides dependencies via Depends().
    """
    # Create service with injected dependencies
    service = SlackUsergroupsService(
        slack_client_factory=slack_client_factory,
        secret_reader=secret_reader,
        settings=settings,
    )

    # Execute business logic
    result = service.reconcile(
        workspaces=request.workspaces,
        dry_run=request.dry_run,
    )

    return result
```

**Dependency providers** (centralized in `qontract_api/dependencies.py`):

```python
from qontract_api.config import get_settings
from qontract_utils.secret_reader import create_secret_reader

def get_secret_reader() -> SecretBackend:
    """FastAPI dependency for secret reader."""
    return create_secret_reader(use_vault=get_settings().vault.enabled)

def get_slack_client_factory(
    cache: CacheBackend = Depends(get_cache_backend),
    settings: Settings = Depends(get_settings),
) -> SlackClientFactory:
    """FastAPI dependency for SlackClientFactory."""
    return SlackClientFactory(
        cache_backend=cache,
        settings=settings,
    )
```

### Pattern 4: Testing with Mocks

Inject mocks for unit testing:

```python
from unittest.mock import MagicMock
from qontract_utils.secret_reader.base import SecretBackend

def test_slack_usergroups_service_reconcile():
    """Test service with mocked dependencies."""
    # Mock dependencies using Protocol types
    mock_secret_reader = create_autospec(SecretBackend)
    mock_secret_reader.read.return_value = "xoxb-mock-token"

    mock_factory = create_autospec(SlackClientFactory)
    mock_slack_client = MagicMock()
    mock_factory.create_workspace_client.return_value = mock_slack_client

    mock_settings = MagicMock(spec=Settings)

    # Create service with mocks
    service = SlackUsergroupsService(
        slack_client_factory=mock_factory,
        secret_reader=mock_secret_reader,
        settings=mock_settings,
    )

    # Test business logic without external dependencies
    result = service.reconcile(
        workspaces=[...],
        dry_run=True,
    )

    # Verify interactions
    assert mock_secret_reader.read.assert_called_once_with(...)
    assert mock_factory.create_workspace_client.assert_called_once_with(...)
    assert result.status == TaskStatus.COMPLETED
```

**Benefits:**

- Services can be tested in isolation (no Vault, no Slack API, no Redis)
- Fast tests (no network calls)
- Deterministic tests (no external dependencies)
- Type-safe mocks via `spec=` parameter

## References

- Related ADRs: ADR-014 (Three-Layer Architecture)
- Implementation example: `qontract_api/integrations/slack_usergroups/service.py`
- Factory example: `qontract_api/integrations/slack_usergroups/router.py`
- SOLID Principles: [Dependency Inversion Principle](https://en.wikipedia.org/wiki/Dependency_inversion_principle)
- Python typing: [Callable](https://docs.python.org/3/library/typing.html#typing.Callable), [Protocol](https://docs.python.org/3/library/typing.html#typing.Protocol)

---

## Notes

**When NOT to use DI:**

Don't inject business data or simple values:

```python
# ❌ DON'T: Inject business data
class UserService:
    def __init__(self, user_id: str):  # Business data, not dependency
        self.user_id = user_id

# ✅ DO: Pass business data to methods
class UserService:
    def __init__(self, database: Database):  # External dependency
        self.database = database

    def get_user(self, user_id: str) -> User:  # Business data as parameter
        return self.database.query(user_id)
```

Only inject external resources (clients, connections, configuration sources), not business values.
