# ADR-008: Client Integration Pattern for qontract-api

**Status:** Proposed
**Date:** 2025-11-14
**Authors:** cassing

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

```python
# reconcile/slack_usergroups_api.py - NEW FILE
"""Slack usergroups reconciliation - via qontract-api.

This integration calls qontract-api instead of executing business logic directly.
Feature flags in reconcile/cli.py control which integration runs (original vs API).
"""

from qontract_api_client import get_api_client

def run(dry_run: bool) -> None:
    """Reconcile Slack usergroups - via qontract-api.

    Calls qontract-api /api/v1/integrations/slack-usergroups/reconcile endpoint.
    No fallback code needed - reconcile/cli.py handles feature flag routing.
    """
    # Call qontract-api
    api_client = get_api_client()

    # Fetch desired state (client-side GraphQL - ADR-002)
    desired_state = fetch_desired_state()

    # Call API
    response = api_client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        json={
            "desired_state": desired_state,
            "dry_run": dry_run,
            "execution_mode": "direct",  # ADR-003
        },
    )

    # Process result
    process_actions(response["actions"])
```

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
    """
    import reconcile.slack_usergroups_api
    run_integration(
        reconcile.slack_usergroups_api,
        ctx,
        workspace_name,
        usergroup_name,
    )
```

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
2. **Safe rollback** - Original integration always available as fallback
3. **Gradual rollout** - Feature flags enable phased deployment
4. **Clear naming** - `_api` suffix immediately identifies API clients
5. **Discoverable** - API client next to original integration
6. **Testing friendly** - Can test both integrations independently
7. **A/B testing** - Compare API vs direct execution performance
8. **Zero-risk deployment** - Feature flag provides instant rollback

### Negative

1. **File duplication** - Two integrations per API-enabled integration
   - **Mitigation:** Only create `_api` for integrations using qontract-api
   - **Mitigation:** Can remove original after 100% rollout (future)

2. **Maintenance** - Two integrations to maintain during transition
   - **Mitigation:** Original integration frozen (no changes during POC)
   - **Mitigation:** Temporary - after full rollout, can deprecate original

3. **CI/CD updates** - Jobs need to call `_api` integration
   - **Mitigation:** Feature flag routing handles this automatically
   - **Mitigation:** Clear migration guide for job updates

## Implementation Guidelines

### For Integration Developers

**Creating new API client integration:**

1. **Create `<integration>_api.py`** alongside original
2. **Copy `run()` signature** from original (same parameters!)
3. **Implement API client logic:**
   - Fetch desired state (client-side GraphQL - ADR-002)
   - Call qontract-api endpoint
   - Process response
4. **Add error handling** for API errors
5. **Test integration independently**

**DO:**

- ✓ Keep original integration unchanged
- ✓ Use `_api` suffix for API client
- ✓ Match `run()` signature exactly
- ✓ Handle API errors gracefully (raise exceptions, don't fallback)
- ✓ Test both integrations independently

**DON'T:**

- ✗ Modify original integration
- ✗ Add feature flag checks in integration code (handled by feature flags in cli.py)
- ✗ Add fallback code to original integration (not needed)
- ✗ Remove original integration during transition (keep as fallback)
- ✗ Forget to add new CLI command in reconcile/cli.py
- ✗ Copy all CLI options from original (API version should be simpler)
- ✗ Keep legacy integration forever (must be removed after stabilization)

### Checklist for New API Client Integration

- [ ] Create `reconcile/<integration>_api.py`
- [ ] Match `run()` signature from `reconcile/<integration>.py` (may have fewer parameters)
- [ ] Implement API client logic (ADR-002: client-side GraphQL)
- [ ] Add error handling for API errors
- [ ] Test integration independently
- [ ] **Add new CLI command** in `reconcile/cli.py` (e.g., `@integration.command() def <integration>_api()`)
- [ ] **Configure simpler options** - Remove sharding, early-exit, extended-early-exit decorators
- [ ] Create feature toggle for `<integration>-api`
- [ ] Update CI/CD jobs to call `qontract-reconcile <integration>-api`
- [ ] Plan cleanup: Schedule removal of legacy integration after stabilization period

### Example Migration

**Before (only original integration):**

```text
reconcile/
└── slack_usergroups.py          # Original - direct execution
```

**After (API client added):**

```text
reconcile/
├── slack_usergroups.py          # Original - UNCHANGED (fallback)
└── slack_usergroups_api.py      # NEW - API client (feature flag controlled)
```

**CI/CD Job:**

```yaml
# Old job (still works)
slack-usergroups-original:
  script:
    - qontract-reconcile slack-usergroups  # Always uses slack_usergroups.py

# New job (uses API client)
slack-usergroups-api:
  script:
    - qontract-reconcile slack-usergroups-api  # Always uses slack_usergroups_api.py
```

**Feature toggles control which integrations are enabled at runtime.**

## References

- Related: [ADR-007](ADR-007-no-reconcile-changes-migrate-utils.md) - No Changes to reconcile/
- Related: [ADR-002](ADR-002-client-side-graphql-fetching.md) - Client-Side GraphQL Fetching
- Related: [ADR-003](ADR-003-direct-vs-queued-execution-modes.md) - Direct vs Queued Execution
- Implementation: `reconcile/slack_usergroups.py` - Original integration
- Implementation: `reconcile/slack_usergroups_api.py` - API client (to be created)

## Notes

This ADR establishes the pattern for how reconcile integrations call qontract-api while keeping original integrations unchanged for safe rollback.

### Transition Timeline

1. **POC Phase** - Create `_api` integrations alongside originals
2. **Gradual Rollout** - Feature flags control which runs (0% → 10% → 50% → 100%)
3. **Full Adoption** - All executions use API (100%)
4. **Stabilization Period** - Monitor API integration in production (e.g., 3-6 months)
5. **Cleanup (Required)** - Delete original integration after stabilization period
6. **Rename (Optional)** - Remove `_api` suffix, becomes canonical integration

### Cleanup: Removing Legacy Integrations

**IMPORTANT: Legacy integrations MUST be removed after successful rollout.**

After the API integration has been stable in production for a sufficient period (e.g., 3-6 months):

1. **Delete original integration** - Remove `reconcile/<integration>.py`
2. **Remove CLI command** - Delete original `@integration.command()` from `reconcile/cli.py`
3. **Remove CI/CD jobs** - Delete legacy job from `.gitlab-ci.yml`
4. **Update documentation** - Remove references to original integration
5. **Optional: Rename** - Remove `_api` suffix (e.g., `slack_usergroups_api.py` → `slack_usergroups.py`)

**Rationale:**

- **Reduce maintenance burden** - No need to maintain two integrations long-term
- **Prevent confusion** - Clear which integration is canonical
- **Code hygiene** - Remove dead code after transition complete
- **Clear signal** - Demonstrates commitment to qontract-api approach

**Transition is temporary, not permanent.** The `_api` pattern is for safe rollout, not long-term coexistence.
