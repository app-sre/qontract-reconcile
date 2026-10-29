# ADR-022: Stateful qontract-api Integrations

**Status:** Proposed
**Date:** 2026-10-29
**Authors:** a-sinclaire
**Supersedes:** N/A
**Superseded by:** N/A

## Context

Some qontract-api integrations must reconcile against an external system that has **no list-all API** (or equivalent). The integration still needs a **durable bookmark** of what it already manages so create/update/delete diffs stay correct across runs.

`ldap-groups-api` ([APPSRE-13597](https://issues.redhat.com/browse/APPSRE-13597)) is the **first** qontract-api integration with this requirement. Review on [PR #5846](https://github.com/app-sre/qontract-reconcile/pull/5846) explored **client-owned** S3 bookmarks (`managed_groups`, client-side task recovery). That splits ownership with qontract-api and complicates cutover (separate `ldap-groups-api` vs legacy `ldap-groups` keys).

Reviewers proposed moving durable state to qontract-api with a **generic** pattern reusable by later migrations ([APPSRE-12896](https://issues.redhat.com/browse/APPSRE-12896)). See [PR #5846 comment](https://github.com/app-sre/qontract-reconcile/pull/5846#issuecomment-6333155181).

### Constraints

- External HTTP to Internal Groups (and peers) stays in qontract-api per ADR-013.
- Integration layout stays ADR-014 (L1 utils, L2 workspace client, L3 router/service/tasks).
- New HTTP `operation_id`s require OPA when policies are enabled (ADR-021).
- Legacy rollback for ldap-groups depends on `state/ldap-groups/managed_groups` remaining authoritative during cutover.

## Decision

Adopt a **server-owned integration state** model for qontract-api integrations that need durable bookmarks:

1. **Client contract:** Reconcile `-api` integrations send **desired state** and `dry_run` only. They do **not** send or persist integration bookmarks once migrated to this pattern.
2. **StateRef:** Each integration registers a fixed server-side reference mapped to a stable persistence key (typically an S3 object path). Reuse pre-migration keys when cutover or rollback depends on them (e.g. `ldap-groups.managed_groups` → `state/ldap-groups/managed_groups` for ldap-groups).
3. **StateStore:** qontract-api provides load/save with a **per-StateRef lock** so only one worker mutates a bookmark at a time.
4. **Worker flow:** On task execution: acquire lock → load bookmark → reconcile external API → **reduce** only **applied** actions into a new bookmark → save (skip save on dry-run) → release lock.
5. **Reducer:** Each integration defines a pure function `(old_bookmark, applied_actions) → new_bookmark`. Transitions depend on that integration's action model and bookmark schema (see **Implementation Guidelines**).
6. **Crash safety:** Use two-phase bookmark updates when a crash mid-task could confuse the next run. **Creates:** update the bookmark **before** the external create (next run re-checks before creating again). **Deletes:** update the bookmark **after** the external delete succeeds. **Updates:** no special bookmark ordering unless the integration doc says otherwise.

### Key Points

- **Server-owned bookmarks:** qontract-api loads, updates, and saves integration state; reconcile `-api` clients do not.
- **One writer per StateRef:** A lock covers load → reconcile → reduce → save so concurrent workers cannot corrupt the same bookmark.
- **Applied actions only:** The new bookmark is produced only from actions that actually succeeded in that run (integration-specific reducer).

## Alternatives Considered

### Alternative 1: Client-owned bookmark (reconcile `-api` client)

The reconcile client loads and saves the bookmark in S3, sends managed resource keys with desired state, and handles async task recovery on the client.

**Pros:**

- Does not require new qontract-api platform work (StateStore, locks, registration).
- Reuses existing reconcile `State` patterns.

**Cons:**

- Two owners for the same logical bookmark during cutover.
- Extra client complexity (recovery polling, stale task refs, dual S3 keys).
- Each new stateful integration may copy the same client-side machinery.

### Alternative 2: No durable bookmark (full discovery each run)

Reconcile derives current managed resources from the external API on every run without a persisted bookmark.

**Pros:**

- No integration bookmark in S3.

**Cons:**

- Requires a list-all API or equivalent full discovery each run.
- Does not apply when the external API only supports targeted reads and mutations (see Context); ldap-groups is in that category.

### Alternative 3: Server-owned StateStore and reducer (Selected)

qontract-api owns bookmarks: StateRef registration, StateStore load/save, per-StateRef locking, and an integration reducer over **applied** actions. Reconcile `-api` clients send desired state and `dry_run` only.

**Pros:**

- Single owner and one persistence path per integration bookmark.
- Reusable platform pattern for later APPSRE-12896 migrations.
- Legacy S3 keys can remain canonical where rollback requires it.
- Crash-safe bookmark rules live with the worker that mutates external systems.

**Cons:**

- Requires new qontract-api components (StateStore, locks, registration).
- Lock contention if many workers hit the same store infrastructure.
  - **Mitigation:** Per-StateRef locks; monitor lock duration and queue depth.

## Consequences

### Positive

- **Simpler clients:** Reconcile `-api` jobs send desired state only; they do not own S3 bookmarks or task recovery for that state.
- **One platform pattern:** Later stateful migrations can reuse StateStore instead of building client-side state again.
- **One place to look:** Bookmarks live in qontract-api; cutover docs name the StateRef and S3 key.
- **Crash rules with the worker:** Bookmark update ordering runs in the Celery task that calls the external API.

### Negative

- **More platform to run:** StateStore, locks, and registration are owned and operated like other qontract-api infrastructure.
- **Per-integration design:** Each integration documents its bookmark shape, reducer, and which operations need two-phase updates.
- **Concurrency limits:** Heavy load on one StateRef can queue workers.
  - **Mitigation:** Per-StateRef locks; watch lock time and Celery backlog.

## Implementation Guidelines

### When to use this pattern

- Integration needs durable state that **cannot** be derived from a full list API on each run.
- Bookmark must survive process restarts and be consistent under concurrent Celery workers.

### When not to use

- State fits in ADR-014 L2 cache only (ephemeral, reconstructible).
- Reconcile can send a complete desired picture with no server bookmark (typical CRUD with list APIs).

### Checklist

- [ ] Register StateRef name → S3 object key; document the mapping in the integration doc.
- [ ] **L3 service** returns **applied actions** from reconcile (ADR-014); reducer is pure over `(bookmark, applied_actions)`.
- [ ] **Celery task:** lock → load bookmark → reconcile → reduce → save; skip save when `dry_run` is true.
- [ ] Document two-phase bookmark rules for crash-sensitive operations, if any (Decision item 6).
- [ ] Add or change routes/models, then regenerate OpenAPI and `qontract_api_client` (do not hand-edit generated files).
- [ ] Add OPA policies for new `operation_id`s (ADR-021).
- [ ] Tests cover reducer logic and dry-run (no bookmark write; no production external mutations).
- [ ] **reconcile `-api` client (ADR-008):** `reconcile/<integration>_api.py`, GraphQL desired state (ADR-002), POST desired payload and `dry_run` only (no client bookmark I/O), poll task status (ADR-003).
- [ ] **Integration doc:** when this pattern applies, StateRef → key, rollback, and cutover.

## References

- [ADR-003](ADR-003-async-only-api-with-blocking-get.md) — async tasks and blocking GET for status
- [ADR-008](ADR-008-qontract-api-client-integration-pattern.md) — reconcile `*_api` client integrations
- [ADR-013](ADR-013-centralize-external-api-calls.md) — external API calls via qontract-api
- [ADR-014](ADR-014-three-layer-architecture-for-external-apis.md) — L1/L2/L3 layout
- [ADR-018](ADR-018-event-driven-communication.md) — events on mutations (orthogonal to state)
- [ADR-021](ADR-021-opa-authorization.md) — OPA authorization
- Design discussion: [PR #5846 comment](https://github.com/app-sre/qontract-reconcile/pull/5846#issuecomment-6333155181)
- PR: [app-sre/qontract-reconcile#5846](https://github.com/app-sre/qontract-reconcile/pull/5846)
