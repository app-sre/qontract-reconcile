# ADR-004: Centralized Rate Limiting via API Wrapper Hooks

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

External APIs (Slack, GitHub, GitLab, AWS) have rate limits:

- **Slack**: Tier-based rate limits (20-100+ requests/minute)
- **GitHub**: 5000 requests/hour for authenticated, lower for unauthenticated
- **GitLab**: 300 requests/minute per user
- **AWS**: Service-specific limits (varies by service/account)

### Problem

Where should rate limiting be implemented?

**Multiple consumers exist:**

1. **qontract-api service layer**: Reconciliation endpoints
2. **Direct integrations**: Existing `reconcile/slack_usergroups.py`
3. **Manual scripts**: Admin tools, debugging scripts
4. **Future consumers**: Other services using SlackApi

**Challenges:**

- Rate limits apply to the workspace/account, not per consumer
- Multiple processes might use same API (distributed rate limiting needed)
- Different tiers have different limits (configuration needed)
- Code duplication if each consumer implements own rate limiting

## Decision

**Implement rate limiting in the API wrapper layer (`qontract_utils`) using the generic hook system (ADR-006), not in service layers or middleware.**

### Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│ qontract-api Service Layer                                  │
│  └─> SlackUsergroupsService                                 │
│       └─> slack_api.update_usergroup_users()                │
│            └─> Automatic rate limiting via hook ✓           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ qontract_utils/slack_api                                 │
│  ├─> Generic hook system (ADR-006)                          │
│  ├─> _metrics_hook (built-in, always active)                │
│  └─> Custom hooks (rate limiting, logging, etc.) - opt-in   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ qontract-api Factory Pattern                                │
│  └─> create_slack_api(workspace, token, cache, settings)    │
│       ├─> Creates TokenBucket (distributed, Redis-backed)   │
│       ├─> Creates rate_limit_hook                           │
│       └─> Returns SlackApi with rate limiting enabled ✓     │
└─────────────────────────────────────────────────────────────┘
```

### Implementation

#### **1. TokenBucket (Distributed Rate Limiter)**

```python
# qontract_api/rate_limit/token_bucket.py

class TokenBucket:
    """Token bucket rate limiter with cache backed state."""

    def __init__(self, cache: CacheBackend, bucket_name: str, capacity: int, refill_rate: float):
        self.cache = cache  # Distributed state via Redis
        self.bucket_name = bucket_name
        self.capacity = capacity
        self.refill_rate = refill_rate

    def acquire(self, tokens: int = 1, timeout: float = 30) -> None:
        """Acquire tokens (sync - for hooks, ADR-005)."""
        # Distributed lock + token calculation + state update
        ...
```

#### **2. Factory with Rate Limiting Hook**

```python
# qontract_api/integrations/slack_usergroups/slack_factory.py

def create_slack_api(workspace_name: str, token: str, cache: CacheBackend, settings: Settings) -> SlackApi:
    """Create SlackApi with rate limiting enabled."""

    # Shared token bucket for workspace (distributed via Redis)
    token_bucket = TokenBucket(
        cache=cache,
        bucket_name=f"slack:{settings.SLACK_RATE_LIMIT_TIER}:{workspace_name}",
        capacity=settings.SLACK_RATE_LIMIT_TOKENS,
        refill_rate=settings.SLACK_RATE_LIMIT_REFILL_RATE,
    )

    def rate_limit_hook(_context: SlackApiCallContext) -> None:
        """Rate limiting hook - blocks until token available."""
        token_bucket.acquire(tokens=1, timeout=30)

    # Metrics hook automatically included (ADR-006)
    return SlackApi(
        workspace_name,
        token,
        before_api_call_hooks=[rate_limit_hook],  # Inject rate limiting
        init_usergroups=True,
    )
```

#### **3. SlackApi Wrapper (No Changes Needed)**

```python
# qontract_utils/slack_api.py

class SlackApi:
    def update_usergroup_users(self, usergroup: str, users: list[str]) -> None:
        # Hook system automatically:
        # 1. Calls _metrics_hook (Prometheus metrics)
        # 2. Calls rate_limit_hook (acquires token) ← Rate limiting!
        # 3. Then calls Slack API
        self._call_hooks("usergroups.users.update", "POST")
        self._sc.usergroups_users_update(usergroup=usergroup, users=users)
```

#### **4. Service Layer (No Rate Limiting Code)**

```python
# qontract_api/integrations/slack_usergroups/service.py

class SlackUsergroupsService:
    def __init__(self, slack_api_factory: SlackApiFactory):
        self.slack_api_factory = slack_api_factory

    async def reconcile(self, desired_state: dict, dry_run: bool):
        slack = self.slack_api_factory.get_client(workspace)
        # Rate limiting happens automatically in SlackApi!
        slack.update_usergroup_users(usergroup, users)
```

### Configuration

```python
# qontract_api/config.py

class Settings(BaseSettings):
    # Slack Rate Limiting
    SLACK_RATE_LIMIT_TIER: str = "tier2"  # tier1, tier2, tier3, tier4
    SLACK_RATE_LIMIT_TOKENS: int = 20     # Bucket capacity
    SLACK_RATE_LIMIT_REFILL_RATE: float = 1.0  # Tokens/second
```

## Alternatives Considered

### Alternative 1: Service Layer Rate Limiting (Rejected)

Implement rate limiting in each service (SlackUsergroupsService, etc.).

**Pros:**

- Service-specific limits possible

**Cons:**

- Code duplication across services
- Direct integrations (`reconcile/slack_usergroups.py`) bypass rate limiting
- Manual scripts bypass rate limiting
- Not reusable
- Inconsistent implementation

### Alternative 2: API Middleware (Rejected)

FastAPI middleware for rate limiting.

**Pros:**

- Centralized at API level

**Cons:**

- Only works for qontract-api, not direct integrations
- Harder to configure per workspace
- Doesn't work for Celery tasks
- Less flexible (can't customize per API wrapper)

### Alternative 3: Per-Integration Implementation (Rejected)

Each integration implements own rate limiting.

**Pros:**

- Maximum flexibility

**Cons:**

- Massive code duplication
- Inconsistent behavior
- Hard to maintain
- Shared limits (same workspace used by multiple integrations) not handled

### Alternative 4: Centralized in API Wrapper via Hooks (Selected)

Implement in `qontract_utils` API wrappers using generic hook system.

**Pros:**

- Single implementation for all consumers
- Reusable across all API wrappers (Slack, GitHub, GitLab, AWS)
- Opt-in (backward compatible with direct integrations)
- Automatic for all API methods (via hook system)
- Distributed (Redis-backed)
- No code duplication

**Cons:**

- Requires factory pattern for opt-in
  - **Mitigation:** Simple factory, clear pattern

## Consequences

### Positive

1. **No code duplication**: Single implementation in API wrapper
2. **Reusable**: All consumers benefit (qontract-api, direct integrations, scripts)
3. **Automatic**: Applies to all API methods via hook system
4. **Distributed**: Redis-backed state works across processes
5. **Opt-in**: Backward compatible (direct integrations work unchanged)
6. **Consistent**: Same rate limiting behavior everywhere
7. **Pattern for all APIs**: Can apply to GitHub, GitLab, AWS wrappers

### Negative

1. **Factory pattern required**: Must use factory to enable rate limiting
   - **Mitigation:** Simple pattern, well-documented
   - Direct integrations can keep using direct constructor

2. **Dependency on cache**: Rate limiting requires Redis/cache backend
   - **Mitigation:** qontract-api already uses Redis
   - Can fall back to in-memory (loses distribution)

## Implementation Guidelines

### For New API Wrappers

1. **Implement generic hook system** (ADR-006)
2. **Create factory function** with rate limiting hook
3. **Configure TokenBucket** with service-specific limits
4. **Document configuration** (tier, capacity, refill_rate)

### For Consumers

**qontract-api**: Always use factory

```python
slack = slack_api_factory.get_client(workspace)  # Rate limiting enabled
```

**Direct integrations**: Continue using direct constructor (no rate limiting)

```python
slack = SlackApi(workspace, token)  # No rate limiting (backward compatible)
```

**Manual scripts**: Can opt-in via factory if needed

## References

- Related: [ADR-006](ADR-006-generic-hook-system-slack-api.md) - Generic Hook System (enables this pattern)
- Implementation: [TokenBucket](../../qontract_api/rate_limit/token_bucket.py), [Factory](../../qontract_api/integrations/slack_usergroups/slack_factory.py)
- External: [Token Bucket Algorithm](https://en.wikipedia.org/wiki/Token_bucket)
