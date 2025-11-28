# qontract-api POC Implementation Guide

**Target Audience**: Developers implementing the qontract-api POC
**Prerequisite**: Read [POC_PLAN.md](POC_PLAN.md) for architecture and decisions

This guide documents **critical architecture decisions**, **non-negotiable patterns**, and **complex refactoring scope**. Standard implementations (FastAPI, Celery, Redis) are left to developer discretion.

---

## Table of Contents

- [Critical Architecture Decisions](#critical-architecture-decisions)
- [Phase 0: Pre-Development](#phase-0-pre-development-day-0-2)
- [Phase 1: Project Setup](#phase-1-project-setup-day-1-2)
- [Phase 2: Core Infrastructure](#phase-2-core-infrastructure-day-3-5)
- [Phase 3: slack_usergroups Integration](#phase-3-slack_usergroups-integration-day-6-10)
- [Rate Limiting Integration](#rate-limiting-integration)
- [Testing Strategy](#testing-strategy)

---

## Critical Architecture Decisions

### 1. Monorepo with uv Workspaces

**Decision**: Integrate qontract-api into qontract-reconcile repository

**Rationale**:

- Shared code (`reconcile.utils`) imported directly
- Atomic changes in same PR
- No version/publish overhead

**Structure**:

```
qontract-reconcile/
├── pyproject.toml                 # Root workspace
├── reconcile/                     # Existing integrations
├── qontract_api/                  # NEW: API server
│   ├── pyproject.toml
│   └── qontract_api/
│       ├── main.py
│       ├── integrations/slack_usergroups/
│       └── tasks/
└── qontract_api_client/           # NEW: Auto-generated client
```

### 2. Client-Side GraphQL Fetching

**Decision**: qontract-api does NOT query qontract-server

**Client workflow**:

1. Client fetches desired_state from qontract-server (GraphQL)
2. Client sends desired_state as POST body to qontract-api
3. API fetches current_state from external systems (Slack, AWS)
4. API calculates diff and returns actions

**Rationale**:

- Clear separation of concerns
- API remains stateless
- No GraphQL client needed in qontract-api

### 3. Custom Redis Lock for Task Deduplication

**Decision**: Implement custom decorator instead of external library

**Rationale**:

- Available libraries (celery-singleton, celery_once) unmaintained (2017-2021)
- Simple implementation (~40 lines)
- Full control over lock behavior

**Implementation**:

```python
def deduplicated_task(lock_key_fn, timeout=600):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            redis_client = Redis.from_url(settings.REDIS_URL)
            lock_key = f"task_lock:{func.__name__}:{lock_key_fn(*args, **kwargs)}"

            lock = redis_client.lock(lock_key, timeout=timeout, blocking=False)
            if not lock.acquire():
                return {"status": "skipped", "reason": "duplicate_task"}

            try:
                return func(*args, **kwargs)
            finally:
                lock.release()
        return wrapper
    return decorator
```

---

## Phase 1: Project Setup (Day 1-2)

### Goal

Monorepo workspace + Docker Compose development environment

### Tasks

- [ ] Create workspace directories
- [ ] Configure root `pyproject.toml` with workspace members
- [ ] Create `qontract_api/pyproject.toml` with dependencies
- [ ] Docker Compose for API + Celery + Redis
- [ ] Basic FastAPI app running

### References

Standard FastAPI + Celery + Redis setup. Use existing qontract-reconcile patterns for:

- Dockerfile with uv
- Environment configuration
- Logging setup

---

## Phase 2: Core Infrastructure

### Goal

FastAPI with Dependency Injection + Celery + Auth

### Critical Implementation: FastAPI Lifespan Pattern

**NON-NEGOTIABLE**: Use lifespan for dependency initialization

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # Startup: Initialize cache backend
    cache = RedisCacheBackend()
    dependencies._cache_backend = cache

    # Startup: Initialize Slack API factory
    from reconcile.utils.secret_reader import create_secret_reader
    secret_reader = create_secret_reader(use_vault=settings.USE_VAULT)
    slack_factory = SlackApiFactory(cache, secret_reader)
    dependencies._slack_api_factory = slack_factory

    yield

    # Shutdown: Close connections
    await cache.close()

app = FastAPI(lifespan=lifespan)
```

**Why**: Global dependencies initialized once, clean shutdown

### Critical Implementation: Async-safe Celery Health Check

**PROBLEM**: `celery_app.control.inspect()` is blocking, blocks event loop

**SOLUTION**: Use `asyncio.to_thread()`

```python
async def check_celery() -> DependencyHealth:
    try:
        import asyncio
        from qontract_api.tasks import celery_app

        # Run blocking Celery call in thread pool (async-safe)
        active_workers = await asyncio.to_thread(
            lambda: celery_app.control.inspect(timeout=5).active()
        )

        if not active_workers:
            return DependencyHealth(
                status=HealthStatus.UNHEALTHY,
                message="No Celery workers available",
            )

        return DependencyHealth(
            status=HealthStatus.HEALTHY,
            message=f"{len(active_workers)} worker(s) active",
        )
    except TimeoutError:
        return DependencyHealth(
            status=HealthStatus.DEGRADED,
            message="Celery check timed out (5s)",
        )
```

### Tasks

- [ ] FastAPI app with lifespan
- [ ] Redis cache backend (async)
- [ ] JWT auth (use python-jose library)
- [ ] Celery app with settings-based config
- [ ] Health check endpoints (liveness + readiness)
- [ ] Error handling middleware
- [ ] Request ID middleware

---

## Phase 3: slack_usergroups Integration

### Goal

Reconciliation endpoint with caching + async task execution

### Service Layer Refactoring Scope

**CRITICAL**: This is a major refactoring task, not trivial!

**Functions to migrate from `reconcile/slack_usergroups.py`**:

1. `_create_usergroups()` (~50 lines)
2. `_update_usergroup_users_from_state()` (~80 lines)
3. `_update_usergroup_from_state()` (~60 lines)
4. Diff calculation logic (~100 lines)

**Strategy**:

```python
class SlackUsergroupsService:
    async def reconcile(self, desired_state: dict, dry_run: bool = True):
        actions = []
        errors = []

        for workspace, workspace_state in desired_state.items():
            slack = self.slack_api_factory.get_client(workspace)

            for usergroup, config in workspace_state.items():
                try:
                    current = await self.fetch_current_state(workspace, usergroup)
                    usergroup_actions = self._calculate_diff(workspace, usergroup, config, current)

                    if not dry_run:
                        await self._execute_actions(slack, usergroup_actions)

                    actions.extend(usergroup_actions)
                except Exception as e:
                    errors.append(f"{workspace}/{usergroup}: {e}")

        return SlackUsergroupsReconcileResponse(
            actions=actions,
            applied_count=len(actions) if not dry_run else 0,
            errors=errors if errors else None,
        )
```

### Tasks

- [ ] Pydantic v2 models for request/response
- [ ] Service layer with caching
- [ ] Task deduplication decorator
- [ ] Celery task for async reconciliation
- [ ] API router (sync + async modes)
- [ ] Dependency injection for required services
- [ ] Client implementation (reconcile/slack_usergroups_api.py)

---

## Rate Limiting Integration

### Decision: Implement in `reconcile/utils/slack_api.py`

**Why**: Avoid code duplication across all services

**Rationale**:

1. Central implementation - all consumers benefit
2. No code duplication in service layers
3. Opt-in via configuration (backward compatible)
4. Consistent behavior across all usage patterns

### Implementation: Optional rate_limiter Parameter

**Changes to `reconcile/utils/slack_api.py`**:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qontract_api.rate_limit.token_bucket import TokenBucket

class SlackApi:
    def __init__(
        self,
        workspace_name: str,
        token: str,
        api_config: SlackApiConfig | None = None,
        rate_limiter: TokenBucket | None = None,  # NEW: Optional
        init_usergroups: bool = True,
        channel: str | None = None,
        **chat_kwargs: Any,
    ) -> None:
        self.workspace_name = workspace_name
        self.rate_limiter = rate_limiter  # NEW
        # ... existing initialization ...

    def _check_rate_limit(self) -> None:
        if self.rate_limiter:
            try:
                self.rate_limiter.acquire_sync(tokens=1, timeout=30)
            except Exception as e:
                logging.warning(f"Rate limit exceeded: {e}")
                raise

    def _api_call(self, method: str, http_verb: str = "GET", **kwargs) -> Any:
        self._check_rate_limit()  # NEW: Before every API call
        slack_request.labels(method, http_verb).inc()
        return self._sc.api_call(method, http_verb=http_verb, **kwargs)

    # All existing methods unchanged - rate limiting happens in _api_call
```

**Key Points**:

- All public methods already use `_api_call()` - no changes needed
- Rate limiting disabled by default (rate_limiter=None)
- qontract-api enables it via factory

### TokenBucket with Sync Support

**qontract_api/rate_limit/token_bucket.py**:

```python
class TokenBucket:
    def __init__(self, cache: CacheBackend, bucket_name: str, capacity: int, refill_rate: float):
        self.cache = cache
        self.bucket_name = bucket_name
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._sync_lock = Lock()

    def acquire_sync(self, tokens: int = 1, timeout: float = 30) -> None:
        """Synchronous version for sync code (SlackApi)."""
        with self._sync_lock:
            start_time = time.time()

            while True:
                current_tokens = self._refill_tokens_sync()

                if current_tokens >= tokens:
                    self._update_bucket_state_sync(current_tokens - tokens, time.time())
                    return

                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    raise QontractAPIException(
                        error_code=ErrorCode.RATE_LIMIT_EXCEEDED,
                        message=f"Rate limit exceeded for {self.bucket_name}",
                        status_code=429,
                    )

                wait_time = min((tokens - current_tokens) / self.refill_rate, timeout - elapsed, 1.0)
                time.sleep(wait_time)
```

### SlackApi Factory

**qontract_api/utils/slack_factory.py**:

```python
class SlackApiFactory:
    def __init__(self, cache: CacheBackend, secret_reader):
        self.cache = cache
        self.secret_reader = secret_reader
        # Shared rate limiter for all workspaces
        self.rate_limiter = TokenBucket(
            cache=cache,
            bucket_name=f"slack:{settings.SLACK_RATE_LIMIT_TIER}",
            capacity=settings.SLACK_RATE_LIMIT_TOKENS,
            refill_rate=settings.SLACK_RATE_LIMIT_REFILL_RATE,
        )

    def get_client(self, workspace_name: str, **kwargs) -> SlackApi:
        token = self.secret_reader.read(f"slack/{workspace_name}/token")

        return SlackApi(
            workspace_name=workspace_name,
            token=token,
            rate_limiter=self.rate_limiter,  # Enable rate limiting
            **kwargs
        )
```

### Usage Patterns

**Direct Integration (unchanged)**:

```python
# reconcile/slack_usergroups.py
slack = SlackApi(workspace_name=ws, token=token)  # No rate limiting
slack.update_usergroup_users(...)
```

**qontract-api (automatic)**:

```python
# qontract_api/integrations/slack_usergroups/service.py
slack = self.slack_api_factory.get_client(workspace)  # Rate limiting enabled
slack.update_usergroup_users(...)  # Rate limited automatically!
```

---

## Testing Strategy

### Unit Testing

#### Mock Fixtures

**qontract_api/tests/conftest.py**:

```python
@pytest.fixture
def mock_secret_reader():
    reader = MagicMock()
    reader.read.side_effect = lambda path: {
        "slack/test-workspace/token": "xoxb-test-token",
        "aws/test-account/credentials": {
            "access_key_id": "AKIATEST",
            "secret_access_key": "test-secret-key",
        },
    }.get(path)
    return reader

@pytest.fixture
def mock_cache():
    cache = MagicMock(spec=CacheBackend)
    cache.get.return_value = None  # Default: cache miss
    return cache
```

#### Celery Eager Mode

**Test Celery tasks synchronously**:

```python
def test_reconcile_task(mock_cache, mock_secret_reader):
    from qontract_api.tasks import celery_app
    celery_app.conf.task_always_eager = True  # Run sync

    result = reconcile_slack_usergroups_task(
        workspace="test", dry_run=True, ...
    )

    assert result["applied_count"] == 0
```

#### Task Deduplication

```python
def test_task_deduplication():
    @deduplicated_task(lambda x, **kw: x, timeout=10)
    def test_task(x):
        return {"status": "completed"}

    result1 = test_task(x="lock-key")
    assert result1["status"] == "completed"

    result2 = test_task(x="lock-key")  # Duplicate
    assert result2["status"] == "skipped"
```

### Integration Testing

**Docker Compose Test Setup**:

```yaml
# qontract_api/tests/integration/docker-compose.test.yml
services:
  api:
    build: ../..
    environment:
      - REDIS_URL=redis://redis:6379/1  # Test DB
      - USE_VAULT=false
  redis:
    image: redis:7-alpine
```

**Run tests**:

```bash
docker compose -f docker-compose.test.yml up -d
pytest qontract_api/tests/integration/ --cov=qontract_api
docker compose -f docker-compose.test.yml down
```

### Testing Checklist

**Before Committing**:

- [ ] Unit tests pass
- [ ] Coverage > 80%
- [ ] Type checking passes (mypy)
- [ ] Linting passes (ruff)

**Before Deploying**:

- [ ] Integration tests pass
- [ ] Health checks return 200
- [ ] Celery workers running
- [ ] JWT auth works

---

## AWS Credentials (Utility Endpoints)

### Configuration

**qontract_api/config.py**:

```python
class Settings(BaseSettings):
    # Vault Integration
    USE_VAULT: bool = True  # False for local dev

    # AWS Credentials
    # POC: Environment variables
    # Production: Vault per account
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
```

### Production Integration

```python
def get_aws_api(account: str, region: str) -> AWSApi:
    # Production: Get from Vault via secret_reader
    from reconcile.utils.secret_reader import create_secret_reader

    secret_reader = create_secret_reader(use_vault=True)
    credentials = secret_reader.read(f"aws/{account}/credentials")

    return AWSApi(AWSStaticCredentials(
        access_key_id=credentials["access_key_id"],
        secret_access_key=credentials["secret_access_key"],
        region=region,
    ))
```

---

## Migration Strategy

See [POC_PLAN.md - Detailed Migration Steps](POC_PLAN.md#detailed-migration-steps) for:

- Feature flag setup (Environment Variable + Unleash)
- Parallel integration registration
- 4-week gradual rollout plan
- Rollback procedures
- Monitoring during migration

---

## Next Steps

1. Complete Phase 0 pre-development validation
2. Start Phase 1 with project setup
3. Weekly sync meetings for feedback
4. After POC: Go/No-Go decision for full migration
