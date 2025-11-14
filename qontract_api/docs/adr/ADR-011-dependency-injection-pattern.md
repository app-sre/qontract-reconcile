# ADR-011: Dependency Injection for External Resources

**Status:** Proposed
**Date:** 2025-11-18
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

We adopt **constructor-based dependency injection** using `Callable` or `Protocol` types for external resources.

Services declare dependencies as constructor parameters with type hints. Callers provide concrete implementations. Dependencies are abstracted as function signatures (Callable) or protocols, not concrete classes.

### Key Points

- **Constructor injection:** Dependencies passed via `__init__` parameters
- **Callable types:** Use `Callable[[InputType], ReturnType]` for simple dependencies
- **Protocol types:** Use `typing.Protocol` for complex dependencies with multiple methods
- **Caller responsibility:** Router/factory provides concrete implementations
- **Type safety:** Full mypy type checking of dependency contracts

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

Inject dependencies as Callable/Protocol types via constructor.

```python
class SlackService:
    def __init__(
        self,
        workspace: str,
        get_secret: Callable[[str], str],  # Dependency abstraction
    ):
        self.workspace = workspace
        self.get_secret = get_secret

    def reconcile(self):
        token = self.get_secret(f"slack/{self.workspace}/token")
        slack_api = SlackApi(token=token)
        # Use slack_api...

# Router provides concrete implementation
def get_secret_from_vault(path: str) -> str:
    return vault_client.read(path)

service = SlackService(
    workspace="app-sre",
    get_secret=get_secret_from_vault
)
```

**Pros:**

- Explicit dependencies (clear what service needs)
- Easy to test (inject mocks)
- No framework dependency
- Type-safe with mypy
- Caller controls implementation
- Follows Dependency Inversion Principle
- Simple and Pythonic

**Cons:**

- More parameters in constructor
  - **Mitigation:** Only inject true external dependencies, not business data
- Manual wiring in router/factory
  - **Mitigation:** Centralize in factory functions

## Consequences

### Positive

- **Testability:** Easy to mock dependencies in unit tests
- **Flexibility:** Swap implementations without changing service code
- **Explicit contracts:** Type hints document dependency requirements
- **Decoupling:** Service doesn't know about Vault, only about "get secret" abstraction
- **Type safety:** mypy validates dependency types at compile time
- **SOLID compliance:** Follows Dependency Inversion Principle
- **No framework lock-in:** Uses standard Python patterns

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

### Pattern 1: Simple Function Dependencies (Callable)

For single-function dependencies, use `Callable` type hints:

```python
from collections.abc import Callable

class MyService:
    """Service with function dependency."""

    def __init__(
        self,
        get_secret: Callable[[str], str],
        get_config: Callable[[str], dict[str, str]],
    ):
        """Initialize service with dependencies.

        Args:
            get_secret: Function to retrieve secrets by path
            get_config: Function to retrieve configuration by key
        """
        self.get_secret = get_secret
        self.get_config = get_config

    def do_work(self) -> None:
        """Business logic using injected dependencies."""
        api_token = self.get_secret("path/to/secret")
        config = self.get_config("my_service")
        # Use api_token and config...
```

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

### Pattern 3: Factory Functions

Centralize dependency wiring in factory functions:

```python
def create_slack_service(
    workspace: str,
    vault_client: VaultClient,
    cache: CacheBackend,
) -> SlackService:
    """Factory function for SlackService with wired dependencies.

    Args:
        workspace: Slack workspace name
        vault_client: Vault client instance
        cache: Cache backend instance

    Returns:
        Configured SlackService instance
    """
    def get_secret(path: str) -> str:
        return vault_client.read(path)

    return SlackService(
        workspace=workspace,
        get_secret=get_secret,
        cache=cache,
    )

# Usage in router
@router.post("/reconcile")
def reconcile_endpoint(workspace: str):
    service = create_slack_service(
        workspace=workspace,
        vault_client=app.state.vault,
        cache=app.state.cache,
    )
    return service.reconcile()
```

### Pattern 4: Testing with Mocks

Inject mocks for unit testing:

```python
def test_slack_service_reconcile():
    """Test service with mocked dependencies."""
    # Mock dependencies
    def mock_get_secret(path: str) -> str:
        return "mock-token-123"

    mock_cache = MockCacheBackend()

    # Create service with mocks
    service = SlackService(
        workspace="test-workspace",
        get_secret=mock_get_secret,
        cache=mock_cache,
    )

    # Test business logic without external dependencies
    result = service.reconcile()

    assert result.success
    assert mock_cache.set.called
```

### Pattern 5: FastAPI Integration

Use with FastAPI's dependency injection:

```python
from fastapi import Depends

def get_vault_client() -> VaultClient:
    """FastAPI dependency for Vault client."""
    return VaultClient(url=settings.vault_url)

def get_cache() -> CacheBackend:
    """FastAPI dependency for cache."""
    return RedisCache(url=settings.redis_url)

@router.post("/reconcile")
def reconcile_endpoint(
    workspace: str,
    vault: VaultClient = Depends(get_vault_client),
    cache: CacheBackend = Depends(get_cache),
):
    """Endpoint with FastAPI dependency injection."""
    service = create_slack_service(
        workspace=workspace,
        vault_client=vault,
        cache=cache,
    )
    return service.reconcile()
```

### Checklist

- [ ] Service dependencies injected via `__init__` parameters
- [ ] Use `Callable[[Input], Output]` for function dependencies
- [ ] Use `Protocol` for complex multi-method dependencies
- [ ] Type hints on all dependency parameters
- [ ] Factory functions for common dependency wiring
- [ ] Mock dependencies in unit tests
- [ ] Document dependency contracts in docstrings

## References

- Related ADRs: ADR-014 (Three-Layer Architecture)
- Implementation example: `qontract_api/integrations/slack_usergroups/service.py`
- Factory example: `qontract_api/integrations/slack_usergroups/router.py`
- SOLID Principles: [Dependency Inversion Principle](https://en.wikipedia.org/wiki/Dependency_inversion_principle)
- Python typing: [Callable](https://docs.python.org/3/library/typing.html#typing.Callable), [Protocol](https://docs.python.org/3/library/typing.html#typing.Protocol)

---

## Notes

**Why Callable instead of concrete types?**

Using `Callable[[str], str]` instead of `VaultClient` means:

- Service doesn't know about VaultClient class
- Can easily swap to environment variables, config files, or different secret stores
- Tests can inject simple lambda functions instead of mocking entire classes

**Example from slack_usergroups:**

```python
# Service defines abstraction
class SlackUsergroupsService:
    def __init__(
        self,
        get_slack_token: Callable[[str], str],  # ← Abstract dependency
        cache: CacheBackend,
    ):
        self.get_slack_token = get_slack_token
        self.cache = cache

# Router provides concrete implementation
def get_slack_token_from_vault(vault_path: str) -> str:
    """TEMPORARY: Use env var, replace with VaultClient."""
    sanitized = vault_path.replace("/", "_").replace("-", "_").upper()
    env_var = f"SLACK_TOKEN_{sanitized}"
    if token := os.getenv(env_var):
        return token
    raise ValueError(f"Token not found: {env_var}")

# Wiring in router
service = SlackUsergroupsService(
    get_slack_token=get_slack_token_from_vault,  # ← Inject implementation
    cache=cache,
)
```

This pattern makes it trivial to:

- Switch to real VaultClient later (change one function)
- Use different secret sources per environment
- Test with mock tokens (`get_slack_token=lambda _: "test-token"`)

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
