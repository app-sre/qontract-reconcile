# LDAP replica failover

**Status: implemented.**

Tracking: https://redhat.atlassian.net/browse/APPSRE-15556

## Problem

Previously, `LdapApi` connected to one LDAP server. When that server was unavailable
and the qontract-api membership cache expired, membership-source consumers failed
closed. This blocked app-interface MR-check dry-runs and caused simultaneous
scheduled reconciliation failures and alerts, even when another replica could
answer the lookup.

The fix is replica failover, not weaker authorization: exhausted replicas and
unresolved groups must still fail closed. Do not introduce stale-cache fallback
or treat lookup failures as empty membership.

## Decision

- Configure a non-empty `ldap.serverUrls` list in the
  `/app-interface/app-interface-settings-1.yml` schema, replacing `serverUrl`.
  Keep one shared `baseDn` and Vault `credentials` reference for the replicas.
- Integrations submit `server_urls` in the LDAP API request. Do not introduce
  qontract-api application settings for LDAP endpoints.
- Use `ldap3.ServerPool` with `ROUND_ROBIN`, `active=False`, and `exhaust=False`.
  Keep the `SAFE_SYNC` connection strategy.
- Let the existing hooks/Stamina mechanism own retry attempts, backoff, and the
  retry budget. Do not add nested `SAFE_RESTARTABLE` or pool retry loops.
- Each retry must cover connection establishment, TLS, authenticated bind, and
  the complete lookup, selecting the next replica after an eligible failure.

`ServerPool` selects endpoints; it is not a pool of reusable authenticated
connections. Round-robin advances when a connection opens, not on every search.
Preserve the pool and its selection state across retry attempts, and close the
failed connection before reopening. Recreating the pool on every attempt loses
that progression. In ldap3 2.9.1, the initial round-robin position is randomized,
so list order does not define a preferred primary.

## Why these pool options?

The following behavior was checked against the pinned ldap3 2.9.1 source.

| Option | Behavior | Consequence for failover |
| --- | --- | --- |
| `FIRST`, active checks enabled | Selects the first server that passes a TCP check. | A replica with working TCP but broken TLS/auth can be selected repeatedly. |
| `FIRST`, `active=False` | Always selects the first server. | No failover without explicit replica exclusion. |
| `ROUND_ROBIN`, active checks enabled | Advances among TCP-reachable servers. | Still needs TLS/auth recovery and adds a separate availability-check loop. |
| `ROUND_ROBIN`, `active=False` | Advances directly to the next server on reopening. | Actual connection, TLS, bind, and lookup determine whether that replica works. |

Active availability checks only open and close a TCP socket. They do not verify
TLS, credentials, LDAP queries, or replication freshness. `FIRST` could support
TLS/auth failover with additional exclusion logic, but round-robin already
provides the required progression without that machinery.

- `active=True` retries availability scans indefinitely when no server passes.
  An outer hook retry cannot stop an inner loop that never returns or raises.
  A numeric `active` bounds the number of scans; in 2.9.1, ordered scans still
  sleep for `POOLING_LOOP_TIMEOUT` (default 10 seconds) after the final failed
  scan before raising `LDAPServerPoolExhaustedError`.
- `exhaust=True` indefinitely excludes replicas that fail the pool's TCP check,
  within that pool state. It does not exclude replicas for TLS, bind, or search
  failures. A numeric value allows rechecking after that many seconds.
- `active=True, exhaust=True` can leave every replica excluded while the pool
  continues waiting indefinitely. These are unsuitable defaults for our API.
- With `active=False`, `exhaust` must be false; ldap3 rejects exhaustion without
  active checks.

Pool state is local to the pool instance, not distributed across workers.
qontract-api currently creates a fresh LDAP client per request; this decision
does not add persistent cross-request health tracking.

## Retry boundary and failure handling

Illustrative sequence (A is whichever replica the pool selects first):

```text
Hook attempt 1: A -> connect -> TLS -> bind -> complete lookup
               eligible failure -> clean up -> raise to hooks
Hook backoff
Hook attempt 2: B -> connect -> TLS -> bind -> restart complete lookup
               success -> return complete result
```

`LdapApi.__enter__` owns cleanup but does not connect eagerly. Each decorated
lookup calls `_paged_search`, whose `_connection_attempt` establishes the
connection, TLS, and bind lazily. Eligible failures disconnect and propagate to
the hook retry loop; the next attempt reopens against the next replica. A
successful connection is reused within the context manager.

ldap3 also caches failed IP addresses independently of `ServerPool.active`.
Without resetting that state, a later visit to a failed replica can skip socket
creation entirely and raise `invalid server address`, even if the replica has
recovered. After an eligible failure, reset only the failed server's address
availability with `Server.reset_availability()` before propagating to the hook
retry loop. Preserve the pool cursor and DNS cache; do not add TCP prechecks or
another retry loop.

`_LDAP_FAILOVER_ERRORS` explicitly includes communication errors, STARTTLS and
certificate errors, bind/authentication failures, and LDAP busy/unavailable
results. Invalid configuration and queries still fail directly. Shared
credentials rejected by every replica produce a bounded failure, not anonymous
fallback. Preserve TLS security settings on failover; do not disable certificate
verification or downgrade transport security to obtain a successful response.
A successful empty result is not a failover trigger.

`get_users` materializes iterable input before entering the decorated retry
boundary, so a consumed generator cannot turn a retry into an empty-user query.
Custom hooks, including explicit retry configuration, remain supported.

On an interrupted paginated lookup, discard accumulated entries and restart
from the first page on the replacement connection. Paging cookies cannot be
assumed portable between replicas. Never return partial results or cache them
as a successful lookup.

## Retry and timeout budget

By default, the hook attempt count is `max(3, len(server_urls))`. The retry budget
is `attempts * (4 * timeout + wait_max)` seconds, allowing for connection, TLS,
bind, a search response, and hook backoff. Both connection and receive timeouts
are explicitly set to `timeout` (default 30 seconds).

Stamina does not interrupt an in-progress call: its retry budget is not a hard
request deadline. A slow multi-page lookup can consume the budget before every
replica is attempted. The previous fixed three-attempt/five-second configuration
could not cover an arbitrary replica list. Keep a successful connection for the
lookup; do not rotate replicas between its pages.

Tests must cover TCP, TLS, and bind failures followed by a healthy replica;
bounded failure when every replica fails; single-replica behavior; and a failure
after the first page that restarts the lookup without partial results. Preserve
existing unresolved-group and confirmed-empty-group semantics.

Connection-establishment regression tests must exercise the real `Server`,
`ServerPool`, `Connection`, and `SyncStrategy.open` paths, mocking DNS/socket I/O
and LDAP responses instead. Mocking `open` itself can verify pool wiring but
cannot detect ldap3's address-availability cache behavior. Cover recovery both
with a singleton pool and after a round-robin pool wraps around.

## API authorization and cache identity

OPA parameter flattening retains list values. The permission key is
`secret.server_urls`; its regex must match **every** supplied endpoint, not only
the first. Empty lists are rejected by the request model and by constrained OPA
parameter matching. Migrate permissions from `secret.server_url` alongside the
request contract; removing endpoint restrictions is not a migration strategy.

The cache prefix hashes the JSON-encoded sorted replica URLs and shared base DN.
Reordering the same replicas preserves the cache namespace; changing the replica
set or base DN creates a new namespace. Existing TTL and fail-closed behavior
are unchanged.

## Quorum verification

**Status: implemented.**

Tracking: https://redhat.atlassian.net/browse/APPSRE-15561

### Problem

Replica failover (above) only reacts to exceptions - a replica that is
reachable, binds successfully, and returns result code 0 looks healthy to
`ServerPool` even if its replication agreement from the real primary is broken
or lagging and its local database only holds a stale/partial copy of the
directory. This was observed live: a query expected to return ~2300 users
returned ~50, with no error raised anywhere in the stack. The one-off
mitigation (a hardcoded minimum-result-count guard in a single integration)
only protected that integration and had to be manually maintained as headcount
changed.

### Decision

- Add a `quorum_count` constructor parameter to `LdapApi` (default 1, i.e.
  disabled). When `quorum_count > 1`, every paginated search re-runs on
  `quorum_count - 1` additional replicas after the primary query succeeds, and
  all results must match exactly. A single disagreement fails the whole lookup
  closed (`LdapQuorumError`) rather than guessing which replica is right.
- Count each hostname only once, ignoring case and a trailing DNS dot. Different
  URL spellings, ports, or transports on the same host cannot add votes. If those
  repeated hosts leave too few distinct replicas, fail closed rather than disable
  verification or lower the required count.
- Reuse the existing `ServerPool` round-robin instead of opening separate
  connections for verification: disconnecting and reconnecting through the
  same `_connection_attempt()` mechanism that powers failover naturally
  advances the pool to a different replica. No new connection machinery.
- Compare complete results, not just which entries are present. A replica can
  hold a stale attribute (e.g. an outdated `memberOf`) on an entry that exists
  on both replicas - DN-only comparison would miss that. Each result set is
  normalized (entries sorted by DN, multi-valued attributes sorted within each
  entry - LDAP guarantees neither order) and hashed with SHA-256 for
  comparison.
- `LdapQuorumError` is a replica-disagreement/cannot-achieve-quorum error, not
  a transient one: it is deliberately absent from `_LDAP_FAILOVER_ERRORS`, so
  it propagates immediately without retry.
- If a verification replica is unreachable, skip it and try the next one
  (bounded by the configured replica count) - an unreachable *verifier* is not
  itself evidence of a mismatch. Only run out of replicas, or an actual
  mismatch, raises.
- If fewer `server_urls` are configured than the requested `quorum_count`,
  disable quorum entirely (fall back to `quorum_count=1`) with a warning log,
  rather than silently verifying against a smaller quorum than configured.
  This keeps local/dev setups with one server working unchanged.
- This replaces the one-off hardcoded safety net in `ldap-users-api`
  (`reconcile/ldap_users_api/integration.py`): the check was specific to that
  integration and needed manual upkeep as headcount changed, while quorum
  verification lives in the shared client and protects every consumer
  (`get_users`, `get_group_members`, `check_groups_exist`,
  `get_github_usernames`) uniformly.

### Cost

Quorum verification runs on every call to `LdapApi`, but Layer 2
(`LdapWorkspaceClient`) caches results for hours (see `LdapSettings` TTLs), so
the extra query against the shared client only happens on a cache miss, not on
every integration run.

### Metric

`qontract_reconcile_external_api_ldap_quorum_mismatch_total{method}` counts
confirmed mismatches, to surface replica health issues to SRE independent of
any single integration's fail-closed abort.

## References

- https://ldap3.readthedocs.io/en/latest/server.html#server-pool
- https://raw.githubusercontent.com/cannatag/ldap3/v2.9.1/ldap3/core/pooling.py
- https://raw.githubusercontent.com/cannatag/ldap3/v2.9.1/ldap3/strategy/base.py
- [Hooks implementation](../hooks.py)
- [LDAP client implementation](api.py)
