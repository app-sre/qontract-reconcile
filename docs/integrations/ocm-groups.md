# OCM Groups Integration

**Last Updated:** 2026-08-18

## Description

Manages OCM (OpenShift Cluster Manager) cluster group memberships for `dedicated-admins` and `cluster-admins` groups. Ensures that users defined in App-Interface roles are members of the correct OCM groups on each cluster, adding missing users and removing unexpected ones.

## Features

- Reconcile `dedicated-admins` and `cluster-admins` group memberships via OCM API
- Concurrent cluster group fetching with configurable thread pool
- Dry-run mode for safe change preview
- Per-action error isolation (one failed cluster doesn't block others)
- Feature-flag support for safe rollout alongside the legacy `ocm-groups` integration

## Desired State Details

Desired state is derived from App-Interface roles and permissions. Each role with `access` entries pointing to clusters and groups defines which users should be members of those groups. The client-side integration queries roles via GraphQL and filters to only include OCM-valid groups (`dedicated-admins`, `cluster-admins`).

## Architecture

**Client-Side (reconcile/ocm_groups_api.py):**

- Fetches clusters from App-Interface (GraphQL)
- Filters for OCM-compatible clusters with the integration enabled
- Fetches desired group memberships from roles/permissions (GraphQL)
- Sends cluster info + desired state to qontract-api
- Polls for task result and logs actions

**Server-Side (qontract_api/integrations/ocm_groups/):**

- Fetches current state (existing group memberships) from OCM API per cluster
- Computes set-based diff between desired and current state
- Generates add_user_to_group / delete_user_from_group actions
- Executes actions against OCM (if not dry-run)

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/ocm-groups/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
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
      "managed_groups": ["dedicated-admins", "cluster-admins"]
    }
  ],
  "desired_state": [
    {"cluster": "my-cluster", "group": "dedicated-admins", "user": "alice"}
  ],
  "dry_run": true
}
```

**Response:** (202 Accepted)

```json
{
  "id": "uuid-string",
  "status": "pending",
  "status_url": "/api/v1/integrations/ocm-groups/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/ocm-groups/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Response:**

```json
{
  "status": "success",
  "actions": [
    {"action_type": "add_user_to_group", "cluster": "my-cluster", "group": "dedicated-admins", "user": "alice"}
  ],
  "applied_actions": [],
  "applied_count": 0,
  "errors": []
}
```

### Models

**Request Fields:**

| Field            | Type                  | Required | Default | Description                                       |
| ---------------- | --------------------- | -------- | ------- | ------------------------------------------------- |
| `ocm_connection` | `OcmConnectionParams` | Yes      | -       | OCM API connection details                        |
| `clusters`       | `list[OcmGroupsCluster]` | Yes   | -       | Clusters with their managed groups                |
| `desired_state`  | `list[OcmGroupUser]`  | Yes      | -       | Desired group memberships                         |
| `dry_run`        | `bool`                | No       | `true`  | If true, only calculate actions without executing |

**Action Types:**

`add_user_to_group`: Add a user to a cluster group.

```json
{"action_type": "add_user_to_group", "cluster": "my-cluster", "group": "dedicated-admins", "user": "alice"}
```

`delete_user_from_group`: Remove a user from a cluster group.

```json
{"action_type": "delete_user_from_group", "cluster": "my-cluster", "group": "dedicated-admins", "user": "bob"}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- Only `dedicated-admins` and `cluster-admins` groups are managed (OCM-valid groups)
- Group creation/deletion is not supported (OCM groups are static)

**Caching:**

- Cluster groups are cached with distributed locking (same TTL as identity providers)
- Cache is invalidated on add/delete user mutations

**Feature Flag:**

- Deploy as `ocm-groups-api` alongside the original `ocm-groups` integration
- Use Unleash feature toggles to switch traffic between legacy and API-based integration
- Instant rollback by disabling the `ocm-groups-api` toggle

## Client Integration

**File:** `reconcile/ocm_groups_api.py`

**CLI Command:** `qontract-reconcile ocm-groups-api`

**No additional arguments** — simpler than the original integration (no sharding, no thread pool size).

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/ocm_groups/](../../qontract_api/qontract_api/integrations/ocm_groups/)
- Client: [reconcile/ocm_groups_api.py](../../reconcile/ocm_groups_api.py)
- Layer 1 (API Client): [qontract_utils/qontract_utils/ocm_api/](../../qontract_utils/qontract_utils/ocm_api/)
- Layer 2 (Workspace Client): [qontract_api/qontract_api/ocm/ocm_workspace_client.py](../../qontract_api/qontract_api/ocm/ocm_workspace_client.py)
- Legacy: [reconcile/ocm_groups.py](../../reconcile/ocm_groups.py) (unchanged, read-only reference)

**ADRs:**

- ADR-002: Client-Side GraphQL Fetching
- ADR-007: No reconcile/ Changes
- ADR-008: Qontract-API Client Integration Pattern
- ADR-014: Three-Layer Architecture
