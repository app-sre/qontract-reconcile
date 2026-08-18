# Quay Repos Integration

**Last Updated:** 2026-08-18

## Description

The `quay-repos-api` integration reconciles Quay.io (and self-hosted Quay) repository state against the desired state declared in App-Interface. It creates, deletes, updates descriptions, and manages visibility (public/private) of repositories in each configured Quay organization. Secrets are passed as Vault references — no token values travel through the client.

## Features

- Creates repositories that exist in desired state but not in Quay
- Deletes repositories present in Quay but absent from desired state (when `managedRepos: true`)
- Updates repository descriptions when they diverge from desired state
- Updates repository visibility (public ↔ private) when it diverges
- Mirrors another org's repo list into the desired state before reconciling
- Detects duplicate repository names across multiple apps at both client and server side
- Dry-run mode calculates actions without executing them
- Skips orgs with no `automationToken` configured

## Desired State Details

Desired state is derived from two sources in App-Interface:

1. **`quay_orgs_v1`** — declares Quay organizations, their instances, automation tokens, and whether repos are managed
2. **`apps_v1.quayRepos`** — each app lists the repos it owns in a given Quay org

An org is included for reconciliation only when:
- `managedRepos: true` or `mirror` is set, **and**
- `automationToken` is set

Repos from all apps for the same `(instance, org_name)` are merged. Duplicate names across apps raise an `IntegrationError` on both client and server.

If `mirror` is set, the mirror org's current repo list (fetched server-side) is merged into the desired state before diffing — so repos that exist in the upstream org but aren't explicitly declared by any app are still preserved.

**Example app config:**

```yaml
$schema: /app-1.yml
name: my-app
quayRepos:
  - org:
      $ref: /quay-orgs/quay.io/myorg.yml
    items:
      - name: my-image
        public: true
        description: "Application container image"
```

## Architecture

**Client-Side (`reconcile/quay_repos_api.py`):**

- Queries `quay_orgs_v1` and `apps_v1` from App-Interface using qenerate-generated types
- Builds a per-org `OrgKey → [QuayRepoItemV1]` map from all apps
- Detects duplicate repo names across apps for the same org (raises `IntegrationError`)
- Constructs `QuayOrgConfig` per eligible org with Vault Secret references (no token values)
- Sends to qontract-api in a single request
- In dry-run: waits for task completion, logs planned actions, raises `IntegrationError` on errors or timeout
- In non-dry-run: fire-and-forget (task runs asynchronously, events are published by the worker)

**Server-Side (`qontract_api/integrations/quay_repos/`):**

- Resolves Quay API tokens from Vault via `SecretManager`
- Fetches current repo state from Quay via `QuayWorkspaceClient` (Layer 2 — cached)
- Expands mirror org repos into desired state before diffing
- Computes diff: calculates create/delete/update_description/update_visibility actions
- Validates no duplicate repo names after mirror expansion
- Executes actions (if not dry-run)
- Publishes one CloudEvent per applied action and one per error via `EventManager`

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/quay-repos/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "orgs": [
    {
      "instance": "quay.io",
      "org_name": "myorg",
      "base_url": "https://quay.io",
      "automation_token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "secret/quay/myorg",
        "field": "token"
      },
      "managed_repos": true,
      "mirror": null,
      "repos": [
        { "name": "my-image", "public": true, "description": "App image" }
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
  "status_url": "/api/v1/integrations/quay-repos/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/quay-repos/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: None = immediate)

**Response:**

```json
{
  "status": "success|failed|pending",
  "actions": [...],
  "applied_count": 0,
  "applied_actions": [],
  "errors": null
}
```

### Models

**Request Fields:**

| Field      | Type              | Required | Default | Description                                       |
| ---------- | ----------------- | -------- | ------- | ------------------------------------------------- |
| `orgs`     | `list[QuayOrgConfig]` | Yes  | -       | Per-org desired state with token references       |
| `dry_run`  | `bool`            | No       | `true`  | If true, only calculate actions without executing |

**QuayOrgConfig Fields:**

| Field               | Type             | Required | Description                                    |
| ------------------- | ---------------- | -------- | ---------------------------------------------- |
| `instance`          | `string`         | Yes      | Quay instance name (e.g. `quay.io`)           |
| `org_name`          | `string`         | Yes      | Quay organization name                         |
| `base_url`          | `string`         | Yes      | Quay instance base URL                         |
| `automation_token`  | `Secret`         | Yes      | Vault reference for the Quay API token         |
| `managed_repos`     | `bool`           | Yes      | Whether repos absent from desired state are deleted |
| `mirror`            | `QuayOrgKey\|null` | No     | Source org to mirror repos from                |
| `repos`             | `list[QuayRepoConfig]` | No | Desired repository list                        |

**Response Fields:**

| Field             | Type                   | Description                                              |
| ----------------- | ---------------------- | -------------------------------------------------------- |
| `status`          | `TaskStatus`           | Task execution status (pending/success/failed)           |
| `actions`         | `list[QuayRepoAction]` | All actions calculated (desired − current)               |
| `applied_count`   | `int`                  | Number of actions applied (0 if dry_run=True)            |
| `applied_actions` | `list[QuayRepoAction]` | Actions successfully applied (non-dry-run only)          |
| `errors`          | `list[string]\|null`   | Per-org errors encountered during reconciliation         |

The integration can perform these reconciliation actions:

`create`:

**Description:** Create a new repository with the specified visibility and description.

**Fields:** `instance`, `org_name`, `repo_name`, `public`, `description`

`delete`:

**Description:** Delete a repository no longer present in desired state.

**Fields:** `instance`, `org_name`, `repo_name`

`update_description`:

**Description:** Update the description of an existing repository.

**Fields:** `instance`, `org_name`, `repo_name`, `description`

`update_visibility`:

**Description:** Change a repository's visibility between public and private.

**Fields:** `instance`, `org_name`, `repo_name`, `public`

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- Only orgs with `managedRepos: true` have repos deleted; others only get creates/updates
- Duplicate repo names across apps raise `IntegrationError` before any mutation

**Managed Resources:**

- Only repos in `repos` field (or mirrored from upstream) are considered desired state
- Repos not in desired state are deleted **only** when `managed_repos: true`

**Caching:**

- Repo list cached per org per Quay instance: `quay:{base_url}:{org}:repos`
- TTL: configurable via `QAPI_QUAY_REPOS_CACHE_TTL` (default: 5 minutes)
- Cache uses double-check locking to prevent stampedes on cache miss

**Events:**

- One CloudEvent published per applied action: `qontract-api.quay-repos.<action_type>`
- One CloudEvent published per error: `qontract-api.quay-repos.error`
- Events are only published in non-dry-run mode

## Required Components

**Vault Secrets:**

- `<automation_token.path>`: Quay organization API token (per org, declared in App-Interface)

**External APIs:**

- Quay API (v1)
  - Base URL: `https://quay.io` (or self-hosted instance URL)
  - Authentication: Bearer token (Quay organization OAuth application token)

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `quay:{base_url}:{org_name}:repos`
- TTL: 300 seconds (default)

## Configuration

**App-Interface Schema:**

```yaml
# quay_orgs_v1 entry
$schema: /quay/quay-org-1.yml
name: myorg
instance:
  $ref: /quay/instances/quay.io.yml
managedRepos: true
automationToken:
  path: app-sre/quay/myorg
  field: token
```

**Integration Settings:**

| Setting                       | Environment Variable             | Default  | Description                          |
| ----------------------------- | -------------------------------- | -------- | ------------------------------------ |
| Quay repos cache TTL          | `QAPI_QUAY_REPOS_CACHE_TTL`     | `300`    | Cache TTL in seconds for repo lists  |

## Client Integration

**File:** `reconcile/quay_repos_api.py`

**CLI Command:** `qontract-reconcile quay-repos-api`

**Client Architecture:**

- Builds desired state entirely from GraphQL before calling qontract-api
- Passes Vault Secret *references* (path + field) — no token values in the request body
- In dry-run: polls task status (with timeout) and logs each calculated action
- In non-dry-run: submits request and returns immediately; Celery worker applies changes and publishes events

## Troubleshooting

**Duplicate repo names across apps**

- **Symptom:** `IntegrationError: quay.io/myorg: duplicate repo name(s) defined across multiple apps: my-image`
- **Cause:** Two or more apps declare the same repo name for the same org
- **Solution:** Remove the duplicate from one of the app definitions in app-interface

**Org skipped with no automationToken**

- **Symptom:** Warning log `No automationToken for quay.io/myorg — skipping`
- **Cause:** The org entry in `quay_orgs_v1` has no `automationToken` field
- **Solution:** Add an `automationToken` Vault reference to the org's app-interface config

**Task timeout in dry-run**

- **Symptom:** `IntegrationError: quay-repos-api: task did not complete within the timeout period`
- **Cause:** Worker is overloaded or Celery task queue is backed up
- **Solution:** Check worker health and Celery queue depth; retry the run

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/quay_repos/](../qontract_api/integrations/quay_repos/)
- Client: [reconcile/quay_repos_api.py](../../reconcile/quay_repos_api.py)

**External:**

- [Quay API Documentation](https://docs.quay.io/api/)
- [App-Interface Quay Schema](https://gitlab.cee.redhat.com/service/app-interface/-/tree/master/schemas/quay)
