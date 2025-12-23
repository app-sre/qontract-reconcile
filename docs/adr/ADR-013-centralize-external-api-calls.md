# ADR-013: Centralize External API Calls in API Gateway

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

Reconciliation integrations often need data from external APIs like PagerDuty (on-call schedules), GitHub (repository collaborators), Jira (issue tracking), or other services. The question is: where should these external API calls happen?

**Current Situation:**

- Reconcile integrations need external data (PagerDuty schedules, GitHub repos, etc.)
- Each integration could call external APIs directly
- Or external API calls could be centralized in qontract-api
- Need to decide architectural pattern for external API access

**Problems with Direct External API Calls from Integrations:**

- **No centralized caching:** Every integration run fetches same data from API
- **No rate limit coordination:** Each integration hits rate limits independently
- **Hard to monitor:** API usage scattered across integrations
- **Secret sprawl:** Authentication credentials needed in every integration
- **Difficult testing:** Must mock external APIs in every integration test
- **No retry logic coordination:** Each integration implements own retry strategy

**Requirements:**

- Minimize external API calls (rate limits, costs, latency)
- Share cached data across multiple integration runs
- Centralized rate limiting across all consumers
- Single point for monitoring API usage
- Centralized secret management
- Consistent retry and error handling
- Easy to test integrations without external APIs

**Constraints:**

- Reconcile integrations run in different processes (pods)
- External APIs have rate limits (e.g., Slack: 20/min (Tier 2), PagerDuty: varies, Jira: 1/sec)
- Some data changes frequently (schedules), some rarely (repo collaborators)
- Need to support multiple external services (PagerDuty, GitHub, Jira, etc.)

## Decision

We adopt **centralized external API access** through qontract-api endpoints.

Reconcile integrations MUST NOT call external APIs directly. Instead, they call qontract-api endpoints which provide cached, rate-limited access to external data.

### Key Points

- **No direct external API calls** from reconcile integrations
- **All external APIs accessed via qontract-api** endpoints
- **Centralized caching** with TTL per data type
- **Centralized rate limiting** across all consumers
- **Single API client implementation** per external service

## Alternatives Considered

### Alternative 1: Direct API Calls from Integrations

Each reconcile integration calls external APIs directly.

```python
# In reconcile/slack_usergroups.py
from pagerduty_client import PagerDutyClient

def build_desired_state(permissions):
    """Build desired state with PagerDuty data."""
    pd_client = PagerDutyClient(token=get_pagerduty_token())

    for permission in permissions:
        if permission.pagerduty:
            # Direct API call - no caching, no rate limit coordination!
            users = pd_client.get_schedule_users(permission.pagerduty.schedule_id)
            # Use users...
```

**Pros:**

- Simple (no API gateway needed)
- Direct control over API calls
- No additional service dependency
- Immediate access to latest data

**Cons:**

- **No caching:** Every integration run hits external API
- **No rate limit coordination:** Each integration counts toward global limit
- **Duplicate code:** Each integration implements same API clients
- **Secret sprawl:** PagerDuty token needed in every integration
- **Hard to monitor:** API usage scattered across integrations
- **Difficult testing:** Must mock PagerDuty in every integration test
- **No retry coordination:** Each integration implements own retry logic
- **Wasted API calls:** Multiple integrations fetch same data

### Alternative 2: Shared Library with Local Caching

Create shared library with in-memory caching for external API calls.

```python
# In qontract_utils/pagerduty.py
from functools import lru_cache

@lru_cache(maxsize=100)
def get_schedule_users(schedule_id: str) -> list[str]:
    """Get users from PagerDuty schedule (cached in memory)."""
    client = PagerDutyClient(token=get_token())
    return client.get_schedule_users(schedule_id)

# In reconcile/slack_usergroups.py
from qontract_utils.pagerduty import get_schedule_users

def build_desired_state(permissions):
    for permission in permissions:
        if permission.pagerduty:
            # Uses shared library with in-memory cache
            users = get_schedule_users(permission.pagerduty.schedule_id)
```

**Pros:**

- Shared code (no duplication)
- Some caching (in-memory, per process)
- Easier to test (mock shared library)
- Centralized secret access

**Cons:**

- **Per-process cache:** Each cron job has own cache (no sharing)
- **No distributed rate limiting:** Each process counts separately
- **Cache doesn't persist:** Lost when process ends
- **No centralized monitoring:** Still scattered across processes
- **Limited cache control:** lru_cache has limited eviction strategies
- **No TTL support:** Can't expire stale data automatically

### Alternative 3: Centralized API Gateway (Selected)

External API calls only in qontract-api, integrations call qontract-api endpoints.

```python
# In qontract_api/integrations/pagerduty/router.py
@router.get("/schedules/{schedule_id}/users")
def get_schedule_users(
    schedule_id: str,
    cache: CacheBackend = Depends(get_cache),
) -> list[str]:
    """Get users from PagerDuty schedule (cached, rate-limited)."""
    cache_key = f"pagerduty:schedule:{schedule_id}:users"

    # Check cache first
    if cached := cache.get(cache_key):
        return json.loads(cached)

    # Fetch from PagerDuty API
    client = PagerDutyClient(token=get_pagerduty_token())
    users = client.get_schedule_users(schedule_id)

    # Cache with TTL
    cache.set(cache_key, json.dumps(users), ttl=300)  # 5 minutes
    return users

# In reconcile/slack_usergroups_api.py
def build_desired_state(permissions):
    """Build desired state via qontract-api."""
    for permission in permissions:
        if permission.pagerduty:
            # Call qontract-api endpoint (cached, rate-limited)
            users = qontract_api.get_pagerduty_schedule_users(
                permission.pagerduty.schedule_id
            )
```

**Pros:**

- **Centralized caching:** All consumers share same cache (Redis/DynamoDB)
- **Rate limit coordination:** Single point tracks all API usage
- **Code reuse:** One PagerDuty client for all integrations
- **Centralized monitoring:** All API calls in one place
- **Secret management:** Secrets only in qontract-api
- **Easy testing:** Integrations just call HTTP endpoint (easy to mock)
- **TTL support:** Cache expires automatically
- **Consistent behavior:** Same retry logic, error handling everywhere

**Cons:**

- **Additional service:** Requires qontract-api deployment
  - **Mitigation:** Already needed for reconciliation API
- **Network hop:** Extra HTTP call adds latency (~5-10ms)
  - **Mitigation:** Negligible compared to external API latency (100-500ms)
  - **Mitigation:** Caching eliminates most external API calls
- **Service dependency:** Integrations depend on qontract-api availability
  - **Mitigation:** Implement proper error handling in integrations
  - **Mitigation:** Monitor qontract-api health

## Consequences

### Positive

- **90%+ reduction in external API calls:** Shared cache across all consumers
- **No rate limit issues:** Centralized rate limiting prevents hitting limits
- **Faster integration runs:** Cache hits return in 1-5ms vs 100-500ms API calls
- **Single client implementation:** One PagerDuty client, one GitHub client, etc.
- **Centralized monitoring:** See all external API usage in one place
- **Better secret management:** Secrets only in qontract-api, not scattered
- **Easier testing:** Integrations mock HTTP calls, not external APIs
- **Consistent error handling:** Same retry logic and error responses
- **Lower costs:** Fewer API calls reduce metered API costs

### Negative

- **Service dependency:** Integrations depend on qontract-api availability
  - **Mitigation:** Proper error handling in integrations
  - **Mitigation:** Health checks and monitoring for qontract-api
  - **Mitigation:** Graceful degradation (fallback to cached data)

- **Extra network hop:** HTTP call to qontract-api adds latency (~5-10ms)
  - **Mitigation:** Negligible compared to external API latency (100-500ms)
  - **Mitigation:** Cache hits eliminate external API calls entirely

- **More endpoints:** Need to implement endpoint for each external API
  - **Mitigation:** Follow standard pattern (easy to scaffold)
  - **Mitigation:** Endpoints are simple (fetch, cache, return)

- **Cache staleness:** Data may be slightly stale (TTL-based)
  - **Mitigation:** Configure appropriate TTL per data type
  - **Mitigation:** Provide cache refresh endpoints if needed

## Implementation Guidelines

### Pattern 1: External API Endpoint

Create qontract-api endpoint for external data:

```python
from fastapi import APIRouter, Depends
from qontract_api.cache import CacheBackend, get_cache
from qontract_api.integrations.pagerduty.client import PagerDutyClient

router = APIRouter(prefix="/api/v1/pagerduty", tags=["pagerduty"])

@router.get("/schedules/{schedule_id}/users")
def get_schedule_users(
    schedule_id: str,
    cache: CacheBackend = Depends(get_cache),
) -> list[str]:
    """Get users from PagerDuty schedule.

    Returns:
        List of user IDs on the schedule

    Caching:
        TTL: 5 minutes (schedules change infrequently)

    Rate Limiting:
        Applied via PagerDutyClient hooks
    """
    cache_key = f"pagerduty:schedule:{schedule_id}:users"

    # Try cache first
    if cached := cache.get(cache_key):
        return json.loads(cached)

    # Fetch from PagerDuty API (rate-limited)
    client = PagerDutyClient(token=get_pagerduty_token())
    users = client.get_schedule_users(schedule_id)

    # Cache with TTL
    cache.set(cache_key, json.dumps(users), ttl=300)
    return users
```

### Pattern 2: Integration Client Call

Call qontract-api endpoint from integration:

```python
# In reconcile/slack_usergroups_api.py
import requests
from reconcile.config import get_qontract_api_url, get_qontract_api_token

def get_pagerduty_schedule_users(schedule_id: str) -> list[str]:
    """Get users from PagerDuty schedule via qontract-api.

    Args:
        schedule_id: PagerDuty schedule ID

    Returns:
        List of user IDs on the schedule
    """
    url = f"{get_qontract_api_url()}/api/v1/pagerduty/schedules/{schedule_id}/users"
    headers = {"Authorization": f"Bearer {get_qontract_api_token()}"}

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    return response.json()

def build_desired_state(permissions):
    """Build desired state with PagerDuty data."""
    for permission in permissions:
        if permission.pagerduty:
            # Call qontract-api (cached, rate-limited)
            users = get_pagerduty_schedule_users(
                permission.pagerduty.schedule_id
            )
            # Use users...
```

### Pattern 3: Cache TTL Configuration

Configure appropriate TTL per data type:

```python
# In qontract_api/config.py
class ExternalApiSettings(BaseModel):
    """Settings for external API caching."""

    # PagerDuty
    pagerduty_schedule_ttl: int = 300  # 5 minutes (changes infrequently)
    pagerduty_escalation_ttl: int = 600  # 10 minutes (very stable)

    # GitHub
    github_collaborators_ttl: int = 1800  # 30 minutes (changes rarely)
    github_repo_info_ttl: int = 3600  # 1 hour (very stable)

    # Jira
    jira_issue_ttl: int = 60  # 1 minute (changes frequently)
    jira_project_ttl: int = 3600  # 1 hour (stable)
```

## References

- Related ADRs: ADR-004 (Centralized Rate Limiting), ADR-014 (Three-Layer Architecture), ADR-015 (Cache Update Strategy)
- Implementation example: `reconcile/slack_usergroups_api.py` (deferred PagerDuty/GitHub calls)
- Future endpoints: `/api/v1/pagerduty/schedules/{id}/users`, `/api/v1/github/repos/{owner}/{repo}/collaborators`

---

## Notes

**Example: PagerDuty Schedules in Slack Usergroups**

The slack_usergroups integration needs PagerDuty schedule data to determine which users should be in on-call Slack usergroups.

**Before (Direct API Calls - AVOIDED):**

```python
# ❌ NOT IMPLEMENTED - would have these problems:
pd_client = PagerDutyClient(token)  # Secret in integration
users = pd_client.get_schedule_users(schedule_id)  # No cache, hits rate limit
```

**After (Via qontract-api):**

```python
# ✅ Future implementation:
users = qontract_api.get_pagerduty_schedule_users(schedule_id)
# - Cached in Redis (shared across all integrations)
# - Rate-limited centrally
# - Monitored in one place
# - No PagerDuty secrets in integration
```

**Benefits:**

- Multiple integrations share cached schedule data
- Single rate limit tracker for all PagerDuty calls
- One PagerDuty client implementation
- Easy to test (mock HTTP endpoint)

**Cache Hit Rates:**

Expected improvement with centralized caching:

- **Without qontract-api:** Every integration run hits PagerDuty API
  - 10 integrations × 20 schedules = 200 API calls/hour
  - Quickly exhausts rate limits

- **With qontract-api:** Cache hit rate ~95%
  - First call: Cache miss, fetch from API
  - Next 299 seconds: Cache hit, return instantly
  - 10 integrations × 20 schedules × 5% miss rate = 10 API calls/hour
  - **95% reduction in API calls**
