# Quay Robot Accounts Integration

**Last Updated:** 2026-08-24

## Description

The `quay-robot-accounts` integration reconciles Quay organization robot accounts against App-Interface. It creates and (explicitly) deletes robots, manages their `managedTeams` membership, and sets repository permissions when `managedRepos` is enabled. Robot tokens returned by Quay on create are not persisted to Vault.

## Features

- Creates robot accounts declared in App-Interface
- Deletes robots only when `delete: true` is set (unmanaged robots are never removed)
- Adds and removes robots from teams listed in the org's `managedTeams`
- Sets, updates, and removes repository permissions when `managedRepos` is true
- Per-org error isolation: one failed organization does not abort the rest
- Dry-run mode calculates actions without calling Quay mutation APIs
- Opt-in via `managedRobotAccounts: true` on the Quay org

## Desired State Details

Desired state is compiled from `quay_robots_v1` in App-Interface. Each robot references a Quay org (`quay_orgs_v1`) which supplies:

- Instance name and URL
- `automationToken` (Vault secret used to authenticate to Quay)
- `managedTeams`, `managedRepos`, `managedRobotAccounts` guardrails

**Example robot definition:**

```yaml
$schema: /dependencies/quay-robot-1.yml
name: ci-bot
description: CI robot
quayOrg:
  $ref: /dependencies/quay/orgs/my-org.yml
teams:
  - sre
repositories:
  - name: my-image
    permission: write
delete: false
```

The org must set `managedRobotAccounts: true`. Teams must be listed in `managedTeams`. Repository permissions require `managedRepos: true`.

## Architecture

**Client-Side (`reconcile/quay_robot_accounts_api.py`):**

- Queries `quay_robots_v1` with org guardrails and automation token refs (generated types in `reconcile/gql_definitions/quay_robot_accounts_api/`)
- Groups robots by instance/org and embeds Vault `Secret` references (never raw tokens)
- Fails closed if a referenced org has no `automationToken`
- Sends the complete desired state to qontract-api in a single request
- In dry-run: waits for task completion and logs planned actions; raises `IntegrationError` on errors or timeout
- In non-dry-run: fire-and-forget (task completes asynchronously, events are published)

**Server-Side (`qontract_api/integrations/quay_robot_accounts/`):**

- Resolves the org automation token from Vault via `SecretManager`
- Validates `managedRobotAccounts`, `managedTeams`, and `managedRepos` guardrails
- Fetches current robots from Quay (only robots present in desired state)
- Computes diff with `diff_iterables` (teams) and `diff_mappings` (repo permissions)
- Executes create/delete/team/repo actions when `dry_run=false`
- Publishes change events for each successfully applied action

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/quay-robot-accounts/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "organizations": [
    {
      "instance_name": "quay-io",
      "instance_url": "quay.io",
      "org_name": "my-org",
      "token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/creds/quay/my-org",
        "field": "token",
        "version": 1
      },
      "managed_teams": ["sre"],
      "managed_repos": true,
      "managed_robot_accounts": true,
      "robots": [
        {
          "name": "ci-bot",
          "description": "CI robot",
          "teams": ["sre"],
          "repositories": [{"name": "my-image", "permission": "write"}],
          "delete": false
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
  "status_url": "/api/v1/integrations/quay-robot-accounts/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/quay-robot-accounts/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: API default timeout)

**Response:**

```json
{
  "status": "success",
  "actions": [],
  "applied_actions": [],
  "applied_count": 0,
  "errors": []
}
```

### Models

**Request Fields:**

| Field           | Type                         | Required | Default | Description                                              |
| --------------- | ---------------------------- | -------- | ------- | -------------------------------------------------------- |
| `organizations` | `list[QuayOrgDesiredState]`  | Yes      | -       | Orgs with robots, guardrails, and automation token refs  |
| `dry_run`       | `bool`                       | No       | `true`  | If true, only calculate actions without executing        |

**Validation Rules:**

- Teams and repository permissions are sorted for deterministic output
- Org must have `managed_robot_accounts=true` or the org is skipped with an error
- Desired teams must be listed in `managed_teams`
- Non-empty `repositories` requires `managed_repos=true`

**Response Fields:**

| Field             | Type                 | Description                                                         |
| ----------------- | -------------------- | ------------------------------------------------------------------- |
| `status`          | `TaskStatus`         | Task execution status (pending/success/failed/skipped)              |
| `actions`         | `list[QuayRobotAction]` | All calculated actions, including any that failed to apply       |
| `applied_actions` | `list[QuayRobotAction]` | Actions successfully applied (non-dry-run only)                  |
| `applied_count`   | `int`                | Number of actions actually applied (0 if dry_run=True)              |
| `errors`          | `list[string]`       | Errors encountered during validation, inventory, or apply           |

The integration can perform these reconciliation actions:

`create`:

**Description:** Create a robot account. Description is set at create time only.

**Fields:**

- `instance_name`, `org_name`, `robot_name`, `description`

`delete`:

**Description:** Delete a robot that has `delete: true` in desired state and currently exists.

**Fields:**

- `instance_name`, `org_name`, `robot_name`

`add_team`:

**Description:** Add the robot (`org+name`) to a managed team.

**Fields:**

- `instance_name`, `org_name`, `robot_name`, `team`

`remove_team`:

**Description:** Remove the robot from a managed team without dropping org membership.

**Fields:**

- `instance_name`, `org_name`, `robot_name`, `team`

`set_repo_permission`:

**Description:** Set or update a robot's role on a repository.

**Fields:**

- `instance_name`, `org_name`, `robot_name`, `repo`, `permission`

`remove_repo_permission`:

**Description:** Remove a robot's permission on a repository.

**Fields:**

- `instance_name`, `org_name`, `robot_name`, `repo`

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- Robots present in Quay but absent from App-Interface are **not** deleted
- Deletion requires an explicit `delete: true` on the robot definition
- Description drift is not reconciled (set on create only)
- Created robot tokens are not written to Vault

**Managed Resources:**

- Only orgs with `managedRobotAccounts=true` are reconciled
- Team membership is limited to `managedTeams`
- Repository permissions are only inventoried/applied when `managedRepos=true`

**Rate Limiting:**

- Quay REST API rate limits apply; inventory is one list-robots call per org plus one permissions call per managed robot when `managedRepos` is true

**Caching:**

- Robot lists: `quay:{instance}:{org}:robots`
- Robot permissions: `quay:{instance}:{org}:robot:{name}:permissions`
- TTL: `QAPI_QUAY__ROBOTS_CACHE_TTL` (default: 3600 seconds)
- Cache is invalidated after successful mutations
- Two-tier caching: memory + Redis with distributed locking

**Other Constraints:**

- Task deduplication: concurrent reconciliations for the same instance/org set are deduplicated (Celery lock, 10-minute timeout)
- Auth and inventory HTTP errors fail closed (recorded as errors; no silent skip)

## Required Components

**Vault Secrets:**

- Per-org Quay `automationToken` (from `quay_orgs_v1`): OAuth/automation token with permission to manage robots, teams, and repo roles

**External APIs:**

- Quay REST API v1
  - Base URL: instance URL from App-Interface (e.g. `https://quay.io`)
  - Authentication: Bearer token
  - Documentation: https://docs.quay.io/api/

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys as listed above
- TTL: 3600 seconds (configurable via `QAPI_QUAY__ROBOTS_CACHE_TTL`)

## Configuration

**App-Interface Schema:**

```yaml
$schema: /dependencies/quay-org-1.yml
name: my-org
instance:
  $ref: /dependencies/quay/instances/quay-io.yml
managedRobotAccounts: true
managedRepos: true
managedTeams:
  - sre
automationToken:
  path: app-sre/creds/quay/my-org
  field: token
  version: 1
```

**Integration Settings:**

| Setting              | Environment Variable           | Default | Description                                      |
| -------------------- | ------------------------------ | ------- | ------------------------------------------------ |
| Robots cache TTL     | `QAPI_QUAY__ROBOTS_CACHE_TTL`  | `3600`  | Cache TTL in seconds for robot lists/permissions |

## Client Integration

**File:** `reconcile/quay_robot_accounts_api.py`

**CLI Command:** `qontract-reconcile quay-robot-accounts-api`

**Arguments and Options:**

- `--org`: Filter reconciliation to a single Quay organization name (optional; default: all orgs)

**Client Architecture:**

1. Queries `quay_robots_v1` including org guardrails and automation token refs
2. Groups robots by instance/org
3. Fails closed if any referenced org lacks `automationToken`
4. Sends one `POST /api/v1/integrations/quay-robot-accounts/reconcile` request
5. In **dry-run**: polls `GET /reconcile/{task_id}` (blocking, 300s timeout), logs actions, raises `IntegrationError` on errors or timeout
6. In **non-dry-run**: returns immediately after queuing (fire-and-forget); applied actions are published as change events by the worker

**Example (dry-run via CLI):**

```bash
qontract-reconcile quay-robot-accounts-api --dry-run

# Filter to one org
qontract-reconcile quay-robot-accounts-api --org my-org --dry-run
```

**Example (direct API call):**

```bash
TOKEN=$(cd qontract_api && make generate-token SUBJECT=dev EXPIRES_DAYS=1 | tail -1)

curl -s -X POST http://localhost:8000/api/v1/integrations/quay-robot-accounts/reconcile \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "organizations": [{
      "instance_name": "quay-io",
      "instance_url": "quay.io",
      "org_name": "my-org",
      "managed_teams": ["sre"],
      "managed_repos": true,
      "managed_robot_accounts": true,
      "robots": [{"name": "ci-bot", "teams": ["sre"], "repositories": [], "delete": false}],
      "token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/creds/quay/my-org",
        "field": "token",
        "version": 1
      }
    }],
    "dry_run": true
  }'
```

## Troubleshooting

**Issue: `KeyError: 'https://vault.example.com'` in task logs**

- **Symptom:** Task fails with `KeyError` on the vault URL
- **Cause:** The qontract-api server is not configured with a Vault backend for that URL
- **Solution:** Set `QAPI_SECRETS__DEFAULT_PROVIDER_URL` and `QAPI_SECRETS__PROVIDERS` in the server's `.env`

**Issue: `cannot manage robot accounts because managedRobotAccounts is not set to true`**

- **Symptom:** Org is skipped with a validation error
- **Cause:** The Quay org in App-Interface does not opt in
- **Solution:** Set `managedRobotAccounts: true` on the org

**Issue: `Quay team X is not defined as a managedTeam`**

- **Symptom:** Validation error naming a team
- **Cause:** The robot's team is not listed in the org's `managedTeams`
- **Solution:** Add the team to `managedTeams` or remove it from the robot

**Issue: 401/403 from Quay**

- **Symptom:** Diff calculation fails for an org; recorded in `errors`
- **Cause:** Automation token missing scopes or expired
- **Solution:** Verify the org `automationToken` in Vault can list/create robots and manage team/repo permissions

**Issue: Task times out in dry-run**

- **Symptom:** `IntegrationError: task did not complete within the timeout period`
- **Cause:** The Celery worker is overloaded or not running
- **Solution:** Check Celery worker health

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/quay_robot_accounts/](../../qontract_api/qontract_api/integrations/quay_robot_accounts/)
- Client: [reconcile/quay_robot_accounts_api.py](../../reconcile/quay_robot_accounts_api.py)
- Layer 1 API client: [qontract_utils/qontract_utils/quay_api/](../../qontract_utils/qontract_utils/quay_api/)
- Layer 2 workspace client: [qontract_api/qontract_api/quay/](../../qontract_api/qontract_api/quay/)
- GQL definitions: [reconcile/gql_definitions/quay_robot_accounts_api/](../../reconcile/gql_definitions/quay_robot_accounts_api/)

**ADRs:**

- [ADR-002: Client-Side GraphQL](../adr/ADR-002-client-side-graphql.md)
- [ADR-003: Async-Only API with Blocking GET](../adr/ADR-003-async-only-api-with-blocking-get.md)
- [ADR-008: Integration Naming (_api suffix)](../adr/ADR-008-qontract-api-client-integration-pattern.md)
- [ADR-011: Dependency Injection](../adr/ADR-011-dependency-injection.md)
- [ADR-012: Pydantic Models](../adr/ADR-012-pydantic-models.md)
- [ADR-014: Three-Layer Architecture](../adr/ADR-014-three-layer-architecture.md)

**External:**

- [Quay API](https://docs.quay.io/api/)
