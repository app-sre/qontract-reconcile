# ADR-008: Qontract-API Client Integration Pattern

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

As qontract-api is developed, existing reconcile integrations need a way to call the API instead of executing business logic directly. This raises several questions:

- **Where do API client integrations live?** Same directory as original integration?
- **How to name them?** `slack_usergroups_api.py` or separate directory?
- **What happens to old integration?** Keep it unchanged or modify it?
- **How to switch between API and direct execution?** Feature flags? Separate jobs?
- **How to handle rollback?** Must be instant and safe

### Current Situation

**Existing reconcile integration (unchanged):**

```text
reconcile/
├── slack_usergroups.py          # Original integration - 300+ lines
│   └── run(dry_run: bool)       # Executes business logic directly
```

**Problem:**

If we want to call qontract-api instead, we have two bad options:

1. **Modify `slack_usergroups.py`** - Violates ADR-007 (no reconcile changes)
2. **Replace `slack_usergroups.py`** - Risky, loses original implementation

**We need a pattern that:**

- ✅ Keeps original integration unchanged
- ✅ Allows gradual rollout (feature flags)
- ✅ Enables instant rollback
- ✅ Clear naming conventions
- ✅ No confusion about which integration does what

## Decision

**Create new API client integrations alongside original integrations, using `_api` suffix naming convention, with feature flag-based routing.**

### Pattern

**File Structure:**

```text
reconcile/
├── slack_usergroups.py          # Original integration - UNCHANGED
│   └── run(dry_run: bool)       # Direct execution (original logic)
│
├── slack_usergroups_api.py      # NEW: API client integration
│   └── run(dry_run: bool)       # Calls qontract-api
```

**Naming Convention:**

- **Original integration:** `<integration_name>.py` - NEVER MODIFIED
- **API client integration:** `<integration_name>_api.py` - NEW FILE
- **Both have same `run()` signature** - Drop-in replacement

### Implementation

**Original integration (unchanged):**

```python
# reconcile/slack_usergroups.py - NEVER MODIFIED
"""Slack usergroups reconciliation - direct execution.

This is the original implementation that executes business logic directly.
DO NOT MODIFY - kept as fallback for rollback.
"""

def run(dry_run: bool) -> None:
    """Reconcile Slack usergroups - direct execution."""
    # Original business logic - UNCHANGED
    desired_state = fetch_desired_state()
    current_state = fetch_current_state()
    actions = calculate_diff(desired_state, current_state)

    if not dry_run:
        apply_actions(actions)
```

**New API client integration:**

API-based integrations MUST inherit from `QontractReconcileApiIntegration` to support asyncio execution:

```python
# reconcile/slack_usergroups_api.py - NEW FILE
"""Slack usergroups reconciliation - via qontract-api.

This integration calls qontract-api instead of executing business logic directly.
Uses QontractReconcileApiIntegration base class to support asyncio.
"""

from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

QONTRACT_INTEGRATION = "slack-usergroups-api"


class SlackUsergroupsIntegrationParams(PydanticRunParams):
    """Parameters for slack-usergroups-api integration."""
    workspace_name: str | None
    usergroup_name: str | None


class SlackUsergroupsIntegration(
    QontractReconcileApiIntegration[SlackUsergroupsIntegrationParams]
):
    """Manage Slack usergroups via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration (asyncio entry point)."""
        # Fetch desired state (client-side GraphQL - ADR-002)
        desired_state = await self.fetch_desired_state()

        # Call qontract-api (auto-generated client supports asyncio)
        response = await reconcile_slack_usergroups(
            client=self.qontract_api_client,
            body=SlackUsergroupsReconcileRequest(
                workspaces=desired_state,
                dry_run=dry_run,
            ),
        )

        # Process result
        await self.process_actions(response.actions)
```

**Key Points:**

- **MUST** inherit from `QontractReconcileApiIntegration` (not `QontractReconcileIntegration`)
- **MUST** implement `async def async_run(self, dry_run: bool) -> None` (not `def run()`)
- **MUST** use Pydantic-based `PydanticRunParams` for type-safe parameters
- **MUST** define `name` property returning integration name
- **Auto-provided** `self.qontract_api_client` - pre-configured asyncio HTTP client

### CLI Command Registration

**Each qontract-api integration gets its own CLI command in `reconcile/cli.py`:**

API client integrations have **different command-line options** than their original counterparts:

- **No sharding options** - Sharding handled by qontract-api
- **No early-exit options** - Not applicable for API-based execution
- **No extended-early-exit** - Caching handled by qontract-api
- **Simpler options** - Only essential parameters (workspace_name, usergroup_name, dry_run)

```python
# reconcile/cli.py

# Original integration command (UNCHANGED)
@integration.command(short_help="Manage Slack User Groups (channels and users).")
@workspace_name
@usergroup_name
@enable_extended_early_exit
@extended_early_exit_cache_ttl_seconds
@log_cached_log_output
@click.pass_context
def slack_usergroups(
    ctx: click.Context,
    workspace_name: str | None,
    usergroup_name: str | None,
    enable_extended_early_exit: bool,
    extended_early_exit_cache_ttl_seconds: int,
    log_cached_log_output: bool,
) -> None:
    import reconcile.slack_usergroups
    run_integration(
        reconcile.slack_usergroups,
        ctx,
        workspace_name,
        usergroup_name,
        enable_extended_early_exit,
        extended_early_exit_cache_ttl_seconds,
        log_cached_log_output,
    )

# NEW: API client integration command
@integration.command(short_help="Manage Slack User Groups via qontract-api.")
@workspace_name
@usergroup_name
@click.pass_context
def slack_usergroups_api(
    ctx: click.Context,
    workspace_name: str | None,
    usergroup_name: str | None,
) -> None:
    """Slack usergroups reconciliation via qontract-api.

    Simpler options - no sharding, no early-exit (handled by qontract-api).
    Uses run_class_integration() to support asyncio execution.
    """
    from reconcile.slack_usergroups_api import (
        SlackUsergroupsIntegration,
        SlackUsergroupsIntegrationParams,
    )

    run_class_integration(
        integration=SlackUsergroupsIntegration(
            SlackUsergroupsIntegrationParams(
                workspace_name=workspace_name,
                usergroup_name=usergroup_name,
            )
        ),
        ctx=ctx,
    )
```

### Asyncio Support

**API-based integrations use asyncio for concurrent execution:**

The `QontractReconcileApiIntegration` base class enforces asyncio patterns:

- **Entry point**: `async def async_run(self, dry_run: bool)` instead of `def run()`
- **HTTP client**: `self.qontract_api_client` - auto-configured `AuthenticatedClient` with asyncio support
- **Concurrent operations**: Use `asyncio.gather()` for parallel external API calls
- **Auto-execution**: `run_class_integration()` automatically calls `asyncio.run(integration.async_run())`

**Example - Concurrent external API calls:**

```python
async def async_run(self, dry_run: bool) -> None:
    # Fetch multiple external resources concurrently
    tasks = [
        get_pagerduty_schedule_users(client=self.qontract_api_client, schedule_id=s.id)
        for s in schedules
    ]
    results = await asyncio.gather(*tasks)  # Run all in parallel

    # Call qontract-api
    response = await reconcile_slack_usergroups(
        client=self.qontract_api_client,
        body=request_data,
    )
```

**Why asyncio?**

- **Performance**: Auto-generated qontract-api client uses httpx AsyncClient
- **Concurrency**: Multiple external API calls in parallel (PagerDuty, GitHub, etc.)
- **Future-proof**: Enables async GraphQL clients and other async operations

**Reference Implementation:** See [reconcile/slack_usergroups_api.py](https://github.com/app-sre/qontract-reconcile/blob/master/reconcile/slack_usergroups_api.py)

### Runtime Switching via Feature Flags

**Feature flags enable runtime switching between legacy and qontract-api integrations:**

- Feature flags control which integration runs at runtime
- Allows instant rollback if errors occur (disable API integration, enable legacy integration)
- Enables gradual rollout (percentage-based enablement)
- No code changes needed for rollback

## Alternatives Considered

### Alternative 1: Modify Original Integration (Rejected)

Modify `reconcile/slack_usergroups.py` to call API when feature flag enabled.

**Pros:**

- No new files
- Single integration

**Cons:**

- **Violates ADR-007** - No reconcile changes allowed
- **Risky** - Modifying production code
- **Merge conflicts** - Harder to merge upstream changes
- **Testing complexity** - Both code paths in same file
- **Rollback risk** - Original code modified

### Alternative 2: Separate Directory (Rejected)

Create separate directory for API client integrations.

```text
reconcile/
├── slack_usergroups.py             # Original
├── integrations_api/
│   └── slack_usergroups.py         # API client
```

**Pros:**

- Clear separation
- No naming conflicts

**Cons:**

- **Confusing** - Two `slack_usergroups.py` files
- **Import complexity** - `from reconcile.integrations_api import slack_usergroups`?
- **Tooling issues** - CI/CD needs to know about two directories
- **Not discoverable** - Hard to find related integrations

### Alternative 3: Suffix Naming `_api` (Selected)

Create new file alongside original with `_api` suffix.

**Pros:**

- **Discoverable** - Both files in same directory
- **Clear naming** - `_api` suffix shows it's API client
- **No reconcile changes** - Original file untouched
- **Drop-in replacement** - Same `run()` signature
- **Easy rollback** - Feature flag + unchanged original
- **Simple CI/CD** - Just change job to call `slack-usergroups-api`

**Cons:**

- **File proliferation** - Two files per integration
  - **Mitigation:** Only for integrations that use API
  - **Mitigation:** Temporary - can remove original after full rollout

## Consequences

### Positive

1. **No reconcile changes** - Original integrations untouched (ADR-007 compliance)
1. **Safe rollback** - Original integration always available as fallback
1. **Gradual rollout** - Feature flags enable phased deployment
1. **Clear naming** - `_api` suffix immediately identifies API clients
1. **Discoverable** - API client next to original integration
1. **Testing friendly** - Can test both integrations independently
1. **A/B testing** - Compare API vs direct execution performance
1. **Zero-risk deployment** - Feature flag provides instant rollback

### Negative

1. **File duplication** - Two integrations per API-enabled integration
   - **Mitigation:** Only create `_api` for integrations using qontract-api
   - **Mitigation:** Can remove original after 100% rollout (future)

1. **Maintenance** - Two integrations to maintain during transition
   - **Mitigation:** Original integration frozen (no changes during POC)
   - **Mitigation:** Temporary - after full rollout, can deprecate original

1. **CI/CD updates** - Jobs need to call `_api` integration
   - **Mitigation:** Feature flag routing handles this automatically
   - **Mitigation:** Clear migration guide for job updates

## Checklist for New API Client Integration

- [ ] Create `reconcile/<integration>_api.py`
- [ ] **Inherit from `QontractReconcileApiIntegration`** (NOT `QontractReconcileIntegration`)
- [ ] **Create Pydantic params class** extending `PydanticRunParams` with integration parameters
- [ ] **Define `QONTRACT_INTEGRATION`** constant (e.g., `"slack-usergroups-api"`)
- [ ] **Implement `name` property** returning `QONTRACT_INTEGRATION`
- [ ] **Implement `async def async_run(self, dry_run: bool)`** (NOT `def run()`)
- [ ] **Use `self.qontract_api_client`** for all HTTP calls to qontract-api
- [ ] **Implement API client logic** (ADR-002: client-side GraphQL)
  - Fetch desired state from qontract-server (GraphQL)
  - Use `asyncio.gather()` for concurrent external API calls (PagerDuty, GitHub, etc.)
  - Call qontract-api reconciliation endpoint
  - Process response and handle errors
- [ ] Add error handling for API errors
- [ ] Test integration independently
- [ ] **Add new CLI command** in `reconcile/cli.py`:
  - Use `@integration.command()` decorator
  - Import integration class and params class
  - Use `run_class_integration()` (NOT `run_integration()`)
  - Pass instantiated integration with params
- [ ] **Configure simpler options** - Remove sharding, early-exit, extended-early-exit decorators
- [ ] Create feature toggle for `<integration>-api`
- [ ] Create a new app-interface qontract-reconcile integration file `/app-sre/integration-1.yml`
- [ ] Plan cleanup: Schedule removal of legacy integration after stabilization period

## References

- Related: [ADR-007](ADR-007-no-reconcile-changes-migrate-utils.md) - No Changes to reconcile/
- Related: [ADR-002](ADR-002-client-side-graphql-fetching.md) - Client-Side GraphQL Fetching
- Related: [ADR-003](ADR-003-async-only-api-with-blocking-get.md) - Async-Only API with Blocking GET Pattern
- Implementation: `reconcile/slack_usergroups.py` - Original integration (unchanged)
- Implementation: `reconcile/slack_usergroups_api.py` - API client integration using `QontractReconcileApiIntegration`
- Implementation: `reconcile/cli.py:1233` - CLI command registration for `slack-usergroups-api`
- Base class: `reconcile/utils/runtime/integration.py` - `QontractReconcileApiIntegration` definition
- Runner: `reconcile/utils/runtime/runner.py` - `run_integration_cfg()` with asyncio support

## Notes

This ADR establishes the pattern for how reconcile integrations call qontract-api while keeping original integrations unchanged for safe rollback.

### Transition Timeline

1. **POC Phase** - Create `_api` integrations alongside originals
1. **Rollout** - Feature flags control which runs
1. **Stabilization Period** - Monitor API integration in production (e.g., 1 week)
1. **Cleanup (Required)** - Delete original integration after stabilization period
1. **Rename (Optional)** - Remove `_api` suffix, becomes canonical integration
