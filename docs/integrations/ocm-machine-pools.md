# OCM Machine Pools Integration

**Last Updated:** 2026-11-10

## Description

Manages OCM (OpenShift Cluster Manager) machine pools and node pools according to App-Interface cluster definitions. Ensures that each cluster's compute pools (replica counts, autoscaling bounds, instance types, labels, taints, subnets) match the desired `machinePools` configuration, creating missing pools, updating drifted ones, and removing pools that are no longer desired — with every safety guard the legacy `ocm-machine-pools` integration had.

Two pool shapes are reconciled, selected by cluster product:

- **Machine pools** (OSD and ROSA classic clusters): plural autoscaling fields (`min_replicas`/`max_replicas`)
- **Node pools** (ROSA HCP / HyperShift clusters): singular autoscaling fields (`min_replica`/`max_replica`), `aws_node_pool` instance type, and `subnet`

## Features

- Create/update/delete machine pools and node pools via the OCM API, per cluster type
- Fixed ↔ autoscaling mode transitions with explicit null serialization (the legacy wire contract)
- All legacy safety guards preserved: immutable-field rejection (`instance_type`, `subnet`), delete-all protection, OSD default-worker protection
- Creates processed before deletes; a failed create blocks its cluster's deletes (a failed pool replacement can never leave a cluster with zero pools)
- Concurrent per-cluster current-state fetching with per-cluster error isolation
- Layer 2 caching of pool lists with invalidation on mutations
- Dry-run mode for safe change preview
- Feature-flag support for safe rollout alongside the legacy `ocm-machine-pools` integration

## Desired State Details

Desired state is derived from each cluster's `machinePools` definition in App-Interface. The client-side integration queries clusters via a dedicated GraphQL query and classifies each cluster by product:

| Product | `spec.hypershift` | Pool shape |
| --- | --- | --- |
| `osd` | — | machine pool |
| `rosa` | `false`/absent | machine pool |
| `rosa` | `true` | node pool |

The OCM cluster ID comes from `spec.id`. Clusters are grouped by OCM instance (`ocm.name`) so that clusters with different credential overrides never share a connection (legacy `OCMMap` parity), and one reconciliation request is sent per group.

Pool fields: `id`, `instance_type`, `replicas` (mutually exclusive with autoscaling), `autoscale` bounds, `labels`, `taints`, and `subnet` (node pools only). Validation rejects `max < min` autoscaling bounds, `autoscaling` together with `replicas`, duplicate pool ids within a cluster, and pool shapes that don't match the cluster type.

## Architecture

**Client-Side (reconcile/ocm_machine_pools_api.py):**

- Fetches clusters with machine pool definitions from App-Interface (GraphQL)
- Filters for enabled clusters with OCM config and `machinePools` present
- Classifies clusters and compiles the desired pool state (machine vs node shape)
- Groups clusters by OCM instance and builds one connection per group
- Sends each group's desired state to qontract-api
- Polls for task results and raises on errors, timeouts, or any non-SUCCESS task status

**Server-Side (qontract_api/integrations/ocm_machine_pools/):**

- Fetches current state (live pools per cluster) from the OCM API concurrently
- Excludes clusters whose fetch failed from the diff (a read failure never looks like "no pools exist")
- Computes the diff keyed by (cluster, pool id) with the legacy `has_diff` semantics
- Enforces the legacy guards before generating mutations
- Executes create → update → delete actions (creates first; failed creates block their cluster's deletes)

**Layers 1 & 2:**

- Layer 1 (`qontract_utils/ocm_api/`): machine pool and node pool CRUD against the per-cluster OCM endpoints, preserving the legacy wire contract (both `replicas` and `autoscaling` always sent with explicit nulls on update; `labels` always sent so PATCH can clear them; empty `taints` omitted; node-pool list pagination ordered by `id`)
- Layer 2 (`qontract_api/ocm/ocm_workspace_client.py`): cached pool list reads (double-checked locking, empty results cache) with cache invalidation on mutations

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/ocm-machine-pools/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "ocm_environment": "ocm-production",
  "ocm_connection": {
    "secret_manager_url": "https://vault.example.com",
    "path": "ocm/prod",
    "ocm_url": "https://api.openshift.com",
    "access_token_url": "https://sso.redhat.com/token",
    "access_token_client_id": "client-id"
  },
  "clusters": [
    {
      "name": "my-cluster",
      "cluster_id": "abc123",
      "cluster_type": "osd",
      "pools": [
        {
          "id": "worker",
          "instance_type": "m5.xlarge",
          "replicas": 3,
          "labels": {"tier": "frontend"}
        }
      ]
    }
  ],
  "dry_run": true
}
```

**Response:** (202 Accepted)

```json
{
  "id": "uuid-string",
  "status": "pending",
  "status_url": "/api/v1/integrations/ocm-machine-pools/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/ocm-machine-pools/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Response:**

```json
{
  "status": "success",
  "actions": [
    {"action_type": "create_machine_pool", "cluster": "my-cluster", "pool_id": "extra"}
  ],
  "applied_actions": [],
  "applied_count": 0,
  "errors": []
}
```

### Models

**Request Fields:**

| Field             | Type                          | Required | Default | Description                               |
| ----------------- | ----------------------------- | -------- | ------- | ----------------------------------------- |
| `ocm_environment` | `str`                         | Yes      | -       | OCM environment name (metric label only)  |
| `ocm_connection`  | `OcmConnectionParams`         | Yes      | -       | OCM API connection details                |
| `clusters`        | `list[DesiredClusterMachinePools]` | Yes | -    | Clusters with their desired pools         |
| `dry_run`         | `bool`                        | No       | `true`  | If true, only calculate actions           |

**Cluster Fields:**

| Field          | Type                        | Description                                        |
| -------------- | --------------------------- | -------------------------------------------------- |
| `name`         | `str`                       | Cluster name (unique within a request)             |
| `cluster_id`   | `str`                       | OCM cluster ID (from App-Interface `spec.id`)      |
| `cluster_type` | `ClusterType`               | `osd`, `rosa`, or `hypershift`                     |
| `pools`        | `list[DesiredMachinePool \| DesiredNodePool]` | Desired pools, shape must match the type |

**Action Types:** `create_machine_pool`, `update_machine_pool`, `delete_machine_pool`, `create_node_pool`, `update_node_pool`, `delete_node_pool` — each carrying `cluster` and `pool_id`.

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- Immutable fields cannot be updated in place: an `instance_type` diff (both pool types) or a `subnet` diff (node pools) fails the task with an error instead of mutating
- A cluster must keep at least one pool — deleting all of a cluster's pools is rejected
- OSD clusters cannot delete their default `worker` machine pool (ROSA classic and HCP clusters can)
- Failed pool creations block their cluster's deletions for that run — a failed replacement never leaves a cluster with zero pools
- Labels and taints updates only apply to new nodes (OCM behavior, logged as a warning)

**Caching:**

- Machine/node pool lists are cached per (environment, cluster) with distributed locking
- Cache is invalidated on create/update/delete mutations

**Feature Flag:**

- Deploy as `ocm-machine-pools-api` alongside the original `ocm-machine-pools`
  integration
- **Exactly one writer per cluster:** both integrations mutate OCM, so a
  cluster must never have both enabled at the same time. To switch a cluster
  over, make a single App-Interface change that adds `ocm-machine-pools` to
  the cluster's `disable.integrations` (disabling the legacy writer) and
  removes `ocm-machine-pools-api` from it (enabling the new writer)
- **Rollback is the reverse:** in one change, remove `ocm-machine-pools`
  from the disable list (re-enable the legacy writer) and add
  `ocm-machine-pools-api` to it (disable the new writer)
- Never run both integrations enabled against the same cluster: duplicate
  mutations can result, and the legacy integration does not invalidate the
  new integration's pool cache, so the new writer can act on stale state

## Client Integration

**File:** `reconcile/ocm_machine_pools_api.py`

**CLI Command:** `qontract-reconcile ocm-machine-pools-api`

**No additional arguments.**

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/ocm_machine_pools/](../../qontract_api/qontract_api/integrations/ocm_machine_pools/)
- Client: [reconcile/ocm_machine_pools_api.py](../../reconcile/ocm_machine_pools_api.py)
- GraphQL query: [reconcile/gql_definitions/ocm_machine_pools_api/](../../reconcile/gql_definitions/ocm_machine_pools_api/)
- Layer 1 (API Client): [qontract_utils/qontract_utils/ocm_api/](../../qontract_utils/qontract_utils/ocm_api/)
- Layer 2 (Workspace Client): [qontract_api/qontract_api/ocm/ocm_workspace_client.py](../../qontract_api/qontract_api/ocm/ocm_workspace_client.py)
- Legacy: [reconcile/ocm_machine_pools.py](../../reconcile/ocm_machine_pools.py) (unchanged, read-only reference)

**ADRs:**

- ADR-002: Client-Side GraphQL Fetching
- ADR-003: Async-Only API with Blocking GET
- ADR-007: No reconcile/ Changes
- ADR-008: Qontract-API Client Integration Pattern
- ADR-011: Dependency Injection Pattern
- ADR-012: Typed Models over Dicts
- ADR-014: Three-Layer Architecture
