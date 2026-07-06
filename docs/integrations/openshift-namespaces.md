# openshift-namespaces

**Last Updated:** 2026-07-06

## Description

Reconciles Kubernetes/OpenShift namespaces across multiple clusters. Ensures that namespaces defined in App-Interface exist on their target clusters and removes namespaces marked for deletion. Uses lightkube as the Kubernetes API client (server-side only).

## Features

- Create namespaces that are defined in App-Interface but don't exist on the cluster
- Delete namespaces that are marked with `delete: true` in App-Interface
- Multi-cluster support — reconcile namespaces across N clusters in a single request
- Cached namespace existence checks with distributed locking (Redis)
- Idempotent operations — creating an existing namespace or deleting a missing one is a no-op

## Desired State Details

Namespaces are defined in App-Interface under the `namespaces` schema. Each namespace has:

- `name`: The namespace name
- `delete`: Boolean flag — `true` means the namespace should be removed from the cluster
- `cluster`: Reference to the target cluster with `name`, `serverUrl`, and `automationToken` (Vault reference)

The client-side integration queries all namespaces via GraphQL, groups them by cluster, and sends the per-cluster desired state to the server.

## Architecture

**Client-Side (reconcile/openshift_namespaces_api.py):**

- Fetches all namespace definitions from App-Interface (GraphQL)
- Applies optional cluster/namespace name filters
- Groups namespaces by cluster
- Constructs `ClusterNamespaces` objects with `Secret` references (Vault paths, NOT actual tokens)
- Sends request to qontract-api
- In dry-run: polls task status and logs planned actions
- In non-dry-run: fires and forgets (task runs async, events published)

**Server-Side (qontract_api/integrations/openshift_namespaces/):**

- Reads automation tokens from Vault using Secret references
- Creates lightkube clients per cluster (Layer 1)
- Checks namespace existence via cached workspace clients (Layer 2)
- Computes diff: desired vs current state
- Generates create/delete actions (plan-and-apply pattern)
- Executes actions if not dry-run
- Publishes CloudEvents for applied actions

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/openshift-namespaces/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "clusters": [
    {
      "cluster_name": "prod-1",
      "server_url": "https://api.prod-1.example.com:6443",
      "automation_token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/integrations-output/openshift-namespaces/prod-1",
        "field": "token"
      },
      "insecure_skip_tls_verify": false,
      "namespaces": [
        {"name": "app-a", "delete": false},
        {"name": "old-app", "delete": true}
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
  "status_url": "/api/v1/integrations/openshift-namespaces/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/openshift-namespaces/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: None = immediate status)

**Response:**

```json
{
  "status": "success",
  "actions": [
    {"action_type": "create_namespace", "cluster": "prod-1", "namespace": "app-a"},
    {"action_type": "delete_namespace", "cluster": "prod-1", "namespace": "old-app"}
  ],
  "applied_actions": [],
  "applied_count": 0,
  "errors": []
}
```

### Models

**Request Fields:**

| Field      | Type                    | Required | Default | Description                                       |
| ---------- | ----------------------- | -------- | ------- | ------------------------------------------------- |
| `clusters` | `list[ClusterNamespaces]` | Yes    | -       | Clusters with desired namespaces                  |
| `dry_run`  | `bool`                  | No       | `true`  | If true, only calculate actions without executing |

**ClusterNamespaces Fields:**

| Field                      | Type                    | Required | Default | Description                                |
| -------------------------- | ----------------------- | -------- | ------- | ------------------------------------------ |
| `cluster_name`             | `string`                | Yes      | -       | Cluster identifier                         |
| `server_url`               | `string`                | Yes      | -       | Kubernetes API server URL                  |
| `automation_token`         | `Secret`                | Yes      | -       | Vault reference for the automation token   |
| `insecure_skip_tls_verify` | `bool`                  | No       | `false` | Skip TLS certificate verification          |
| `namespaces`               | `list[DesiredNamespace]` | No      | `[]`    | Desired namespaces for this cluster        |

**DesiredNamespace Fields:**

| Field    | Type     | Required | Default | Description                          |
| -------- | -------- | -------- | ------- | ------------------------------------ |
| `name`   | `string` | Yes      | -       | Namespace name                       |
| `delete` | `bool`   | No       | `false` | True = namespace should be removed   |

**Response Fields:**

| Field             | Type                   | Description                                            |
| ----------------- | ---------------------- | ------------------------------------------------------ |
| `status`          | `TaskStatus`           | Task execution status (pending/success/failed/skipped) |
| `actions`         | `list[NamespaceAction]` | All planned actions                                   |
| `applied_actions` | `list[NamespaceAction]` | Actions that were applied (empty if dry_run)          |
| `applied_count`   | `int`                  | Number of actions actually applied (0 if dry_run=True) |
| `errors`          | `list[string]`         | List of errors encountered during reconciliation       |

`create_namespace`:

**Description:** Create a namespace on a cluster. Idempotent — if the namespace already exists (HTTP 409), it is silently returned.

**Fields:**

- `cluster`: Cluster name
- `namespace`: Namespace name

**Example:**

```json
{
  "action_type": "create_namespace",
  "cluster": "prod-1",
  "namespace": "app-a"
}
```

`delete_namespace`:

**Description:** Delete a namespace from a cluster. Idempotent — if the namespace doesn't exist (HTTP 404), it is silently ignored.

**Fields:**

- `cluster`: Cluster name
- `namespace`: Namespace name

**Example:**

```json
{
  "action_type": "delete_namespace",
  "cluster": "prod-1",
  "namespace": "old-app"
}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- Plan-and-apply pattern: the complete diff is calculated before any action is executed
- Individual action failures do not stop remaining actions — errors are collected and reported
- Create and delete operations are idempotent (safe to retry)

**Managed Resources:**

- Only namespaces explicitly listed in the request are managed
- Namespaces not in the request are NOT touched (no orphan deletion)
- Namespaces with `delete: false` (default) are ensured to exist
- Namespaces with `delete: true` are ensured to not exist

**Caching:**

- Namespace existence is cached per-cluster in Redis with double-check locking
- Cache key: `kubernetes:{cluster_name}:namespace:{namespace_name}:exists`
- TTL: 300 seconds (5 minutes), configurable via `QAPI_KUBERNETES__NAMESPACE_CACHE_TTL`
- Cache is invalidated after create/delete operations

**Other Constraints:**

- No secret values cross the API boundary — only Vault references (`Secret` objects with path/field)
- Server resolves actual tokens from Vault at execution time

## Required Components

**Vault Secrets:**

- Per-cluster automation token at the path defined in `automation_token.path`

**External APIs:**

- Kubernetes/OpenShift API (per cluster)
  - Authentication: Bearer token (from Vault)
  - Client library: lightkube (server-side Layer 1)

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `kubernetes:{cluster_name}:namespace:{name}:exists`
- TTL: 300 seconds (configurable)

## Configuration

**Integration Settings:**

| Setting                | Environment Variable                       | Default | Description                        |
| ---------------------- | ------------------------------------------ | ------- | ---------------------------------- |
| Namespace cache TTL    | `QAPI_KUBERNETES__NAMESPACE_CACHE_TTL`     | `300`   | Namespace existence cache TTL (s)  |

## Client Integration

**File:** `reconcile/openshift_namespaces_api.py`

**CLI Command:** `qontract-reconcile openshift-namespaces-api`

**Arguments and Options:**

- `--cluster-name`: Filter by cluster name (optional)
- `--namespace-name`: Filter by namespace name (optional)

**Client Architecture:**

- Inherits from `QontractReconcileApiIntegration`
- Uses `async_run()` entry point (not `run()`)
- Fetches desired state from GraphQL via `get_namespaces_minimal()`
- Compiles per-cluster desired state with `Secret` references
- In dry-run: polls task status via `poll_task_status()`, logs actions, raises `IntegrationError` on failures
- In non-dry-run: fire-and-forget (task runs async in background, events published via CloudEvents)

## Troubleshooting

**Issue 1: Namespace creation fails with 403 Forbidden**

- **Symptom:** `ForbiddenError` in task result errors
- **Cause:** The automation token doesn't have permission to create namespaces on the cluster
- **Solution:** Verify the Vault secret path has a token with sufficient RBAC permissions

**Issue 2: Task remains in PENDING status**

- **Symptom:** GET endpoint returns `status: pending` even after timeout
- **Cause:** Celery worker not running or not processing the task queue
- **Solution:** Check Celery worker health and Redis connectivity

**Issue 3: Cache stale after manual namespace changes**

- **Symptom:** Integration reports no action needed, but namespace doesn't exist
- **Cause:** Namespace was deleted outside of the integration, cache still has `exists: true`
- **Solution:** Wait for cache TTL (5 minutes) to expire, or restart the worker to clear in-memory cache

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/openshift_namespaces/](../../qontract_api/qontract_api/integrations/openshift_namespaces/)
- Client: [reconcile/openshift_namespaces_api.py](../../reconcile/openshift_namespaces_api.py)
- Layer 1 (K8s API): [qontract_utils/qontract_utils/kubernetes/](../../qontract_utils/qontract_utils/kubernetes/)
- Layer 2 (Cache): [qontract_api/qontract_api/kubernetes/](../../qontract_api/qontract_api/kubernetes/)

**ADRs:**

- [ADR-003: Async-Only API with Blocking GET](../adr/ADR-003-async-only-api-with-blocking-get.md)
- [ADR-008: Integration Naming Pattern](../adr/ADR-008-qontract-api-client-integration-pattern.md)
- [ADR-013: Centralize External API Calls](../adr/ADR-013-centralize-external-api-calls.md)
- [ADR-014: Three-Layer Architecture](../adr/ADR-014-three-layer-architecture-for-external-apis.md)
- [ADR-018: Event-Driven Communication](../adr/ADR-018-event-driven-communication.md)
