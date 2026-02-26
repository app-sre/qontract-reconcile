# Glitchtip Project Alerts

**Last Updated:** 2026-02-26

## Description

The `glitchtip-project-alerts-api` integration manages project alert configurations in [Glitchtip](https://glitchtip.com/) instances. It reconciles the desired alert state defined in App-Interface against the current state in Glitchtip, creating, updating, or deleting alerts as needed. It also supports automatic Jira ticket creation via the Glitchtip-Jira-Bridge service.

## Features

- Manage project alerts across multiple Glitchtip instances and organizations
- Support for email and webhook alert recipients
- Automatic Jira ticket creation via Glitchtip-Jira-Bridge (direct project or escalation policy)
- Multi-instance reconciliation in a single API call
- Two-tier caching (memory + Redis) for Glitchtip API responses with distributed locking
- Dry-run mode enabled by default for safe planning before applying changes
- Deduplication of concurrent reconciliation tasks per instance set
- Write-through cache invalidation after alert mutations

## Desired State Details

The desired state is defined in App-Interface through two GraphQL types:

- **`glitchtip_instances_v1`**: Glitchtip instance configuration (URL, automation token, optional Jira Bridge URL and token, timeouts)
- **`glitchtip_projects_v1`**: Per-project alert configuration, including alert rules (name, quantity, timespan) and recipients (email or webhook), plus optional Jira integration

Each Glitchtip project belongs to an organization which belongs to an instance. The client groups projects by organization and builds the complete desired state hierarchy (`instance → organization → project → alerts`) before sending it to the API.

The alert name `"Glitchtip-Jira-Bridge-Integration"` is reserved and managed automatically by the Jira integration. Manually specifying this name in App-Interface will raise an error.

Webhook URLs within a single project must be unique. Duplicate webhook URLs across alerts of the same project will cause the reconciliation to abort.

## Architecture

**Client-Side (`reconcile/glitchtip_project_alerts_api/integration.py`):**

- Fetches all Glitchtip instances from App-Interface (`glitchtip_instances_v1`)
- Fetches all Glitchtip projects from App-Interface (`glitchtip_projects_v1`), grouped by instance
- Builds the desired state: resolves webhook URL secrets from Vault, builds Jira alert webhooks
- Sends the complete desired state to qontract-api via `POST /reconcile`
- Polls `GET /reconcile/{task_id}` with a 300-second timeout for the result
- Logs all actions and exits with code 1 if errors occurred

**Server-Side (`qontract_api/integrations/glitchtip_project_alerts/`):**

- Retrieves Glitchtip API tokens from the configured secret manager (Vault)
- Fetches current state from Glitchtip (organizations, projects, alerts) with two-tier caching
- Computes a diff between current and desired alerts using `qontract_utils.differ.diff_iterables`
- Generates `create`, `update`, and `delete` actions per alert
- Executes actions against the Glitchtip API (if `dry_run=False`)
- Invalidates relevant cache entries after each mutation
- Returns a structured result with all actions, applied count, and any errors

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/glitchtip-project-alerts/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "instances": [
    {
      "name": "my-glitchtip",
      "console_url": "https://glitchtip.example.com",
      "token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/glitchtip/my-glitchtip",
        "field": "token"
      },
      "read_timeout": 30,
      "max_retries": 3,
      "organizations": [
        {
          "name": "my-org",
          "projects": [
            {
              "name": "my-project",
              "slug": "my-project",
              "alerts": [
                {
                  "name": "high-error-rate",
                  "timespan_minutes": 60,
                  "quantity": 100,
                  "recipients": [
                    {"recipient_type": "email"},
                    {"recipient_type": "webhook", "url": "https://hooks.example.com/alert"}
                  ]
                }
              ]
            }
          ]
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
  "status_url": "/api/v1/integrations/glitchtip-project-alerts/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/glitchtip-project-alerts/reconcile/{task_id}?timeout=300
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion. Defaults to the server's configured default timeout. Returns HTTP 408 if the task is still pending after the timeout.

**Response:**

```json
{
  "status": "success|failed|pending",
  "actions": [...],
  "applied_count": 0,
  "errors": null
}
```

### Models

**Request Fields:**

| Field         | Type                    | Required | Default | Description                                                          |
| ------------- | ----------------------- | -------- | ------- | -------------------------------------------------------------------- |
| `instances`   | `list[GlitchtipInstance]` | Yes    | -       | List of Glitchtip instances to reconcile                             |
| `dry_run`     | `bool`                  | No       | `true`  | If true, only calculate actions without executing                    |

**GlitchtipInstance Fields:**

| Field           | Type                          | Required | Default | Description                               |
| --------------- | ----------------------------- | -------- | ------- | ----------------------------------------- |
| `name`          | `string`                      | Yes      | -       | Unique instance identifier                |
| `console_url`   | `string`                      | Yes      | -       | Glitchtip instance base URL               |
| `token`         | `Secret`                      | Yes      | -       | Vault secret reference for the API token  |
| `read_timeout`  | `int`                         | No       | `30`    | HTTP read timeout in seconds              |
| `max_retries`   | `int`                         | No       | `3`     | Max HTTP retries on failure               |
| `organizations` | `list[GlitchtipOrganization]` | No       | `[]`    | Desired organizations with project alerts |

**GlitchtipProjectAlert Fields:**

| Field              | Type                                  | Required | Description                                      |
| ------------------ | ------------------------------------- | -------- | ------------------------------------------------ |
| `name`             | `string`                              | Yes      | Alert name (unique identifier within a project)  |
| `timespan_minutes` | `int`                                 | Yes      | Time window in minutes for alert evaluation      |
| `quantity`         | `int`                                 | Yes      | Number of events to trigger the alert            |
| `recipients`       | `list[GlitchtipProjectAlertRecipient]` | No      | List of alert recipients                         |

**GlitchtipProjectAlertRecipient Fields:**

| Field            | Type           | Required | Description                                        |
| ---------------- | -------------- | -------- | -------------------------------------------------- |
| `recipient_type` | `email\|webhook` | Yes    | Recipient type                                     |
| `url`            | `string`       | No       | Webhook URL (required for webhook, empty for email) |

**Validation Rules:**

- Webhook recipients must have a non-empty `url`; email recipients must have an empty `url`
- Alert names must be unique within a project
- Project slug defaults to a slugified version of the project name if not provided
- The alert name `"Glitchtip-Jira-Bridge-Integration"` is reserved

**Response Fields:**

| Field           | Type                   | Description                                            |
| --------------- | ---------------------- | ------------------------------------------------------ |
| `status`        | `TaskStatus`           | Task execution status (`pending`/`success`/`failed`)   |
| `actions`       | `list[Action]`         | List of actions calculated/performed                   |
| `applied_count` | `int`                  | Number of actions actually applied (0 if `dry_run=True`) |
| `errors`        | `list[string] \| None` | List of errors encountered during reconciliation       |

The integration can perform these reconciliation actions:

`create`:

**Description:** Create a new project alert in Glitchtip.

**Fields:**

- `action_type`: `"create"`
- `instance`: Glitchtip instance name
- `organization`: Organization name
- `project`: Project slug
- `alert_name`: Alert name

**Example:**

```json
{
  "action_type": "create",
  "instance": "my-glitchtip",
  "organization": "my-org",
  "project": "my-project",
  "alert_name": "high-error-rate"
}
```

`update`:

**Description:** Update an existing project alert in Glitchtip (replaces all fields including recipients).

**Fields:**

- `action_type`: `"update"`
- `instance`: Glitchtip instance name
- `organization`: Organization name
- `project`: Project slug
- `alert_name`: Alert name

**Example:**

```json
{
  "action_type": "update",
  "instance": "my-glitchtip",
  "organization": "my-org",
  "project": "my-project",
  "alert_name": "high-error-rate"
}
```

`delete`:

**Description:** Delete a project alert from Glitchtip.

**Fields:**

- `action_type`: `"delete"`
- `instance`: Glitchtip instance name
- `organization`: Organization name
- `project`: Project slug
- `alert_name`: Alert name

**Example:**

```json
{
  "action_type": "delete",
  "instance": "my-glitchtip",
  "organization": "my-org",
  "project": "my-project",
  "alert_name": "stale-alert"
}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- The integration exits with code 1 if the task does not complete within 300 seconds
- The Celery task has a deduplication lock: concurrent reconciliations for the same set of instances are skipped (returned as `{"status": "skipped", "reason": "duplicate_task"}`)
- Task lock timeout is 600 seconds

**Managed Resources:**

- Only alerts for projects and organizations that exist in both App-Interface and Glitchtip are reconciled
- If a Glitchtip organization or project listed in the desired state is not found in the instance, it is logged as a warning and skipped (no error)
- Alerts that exist in Glitchtip but are not in the desired state are **deleted**

**Caching:**

| Resource      | Cache Key Pattern                                        | TTL    |
| ------------- | -------------------------------------------------------- | ------ |
| Organizations | `glitchtip:<instance>:organizations`                     | 1 hour |
| Projects      | `glitchtip:<instance>:<org_slug>:projects`               | 1 hour |
| Alerts        | `glitchtip:<instance>:<org_slug>:<project_slug>:alerts`  | 1 hour |

Cache uses double-checked locking with distributed Redis locks for thread safety. After any alert mutation (create/update/delete), the relevant alerts cache key is invalidated.

**Other Constraints:**

- Webhook URLs within a project's alerts must be unique; duplicate URLs cause the client-side build to abort
- The alert name `"Glitchtip-Jira-Bridge-Integration"` is reserved for the automatic Jira integration

## Required Components

**Vault Secrets:**

- `<glitchtip_instance.automation_token.path>`: Glitchtip API token for the automation user
- `<glitchtip_instance.glitchtip_jira_bridge_token.path>` (optional): Bearer token for the Glitchtip-Jira-Bridge webhook

**External APIs:**

- Glitchtip REST API
  - Base URL: configured per instance via `consoleUrl`
  - Authentication: Bearer token (from Vault)
  - Client: `qontract_utils.glitchtip_api.GlitchtipApi`

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `glitchtip:<instance>:<resource>` pattern
- TTL: 3600 seconds (1 hour) for all resource types

## Configuration

**App-Interface Schema:**

Glitchtip instances are configured as `glitchtip_instances_v1` resources:

```yaml
$schema: /glitchtip/instance-1.yml
name: my-glitchtip
description: Production Glitchtip instance
consoleUrl: https://glitchtip.example.com
automationUserEmail:
  path: app-sre/glitchtip/my-glitchtip
  field: email
automationToken:
  path: app-sre/glitchtip/my-glitchtip
  field: token
readTimeout: 30
maxRetries: 3
# Optional: Glitchtip-Jira-Bridge integration
glitchtipJiraBridgeAlertUrl: https://gjb.example.com/alert
glitchtipJiraBridgeToken:
  path: app-sre/gjb/token
  field: token
```

Glitchtip projects are configured as `glitchtip_projects_v1` resources:

```yaml
$schema: /glitchtip/project-1.yml
name: my-service
projectId: my-service  # Glitchtip project slug
organization:
  name: my-org
  instance:
    name: my-glitchtip
alerts:
  - name: high-error-rate
    description: "Alert on high error rate"
    quantity: 100
    timespanMinutes: 60
    recipients:
      - provider: email
      - provider: webhook
        url: https://hooks.example.com/alert
# Optional: Jira integration (direct project or escalation policy)
jira:
  project: MY-JIRA-PROJECT
  labels:
    - glitchtip
  components:
    - my-service
```

**Integration Settings:**

| Setting                      | Environment Variable                              | Default | Description                          |
| ---------------------------- | ------------------------------------------------- | ------- | ------------------------------------ |
| Organizations cache TTL      | `QAPI_GLITCHTIP_ORGANIZATIONS_CACHE_TTL`          | `3600`  | Cache TTL for organizations (seconds)|
| Projects cache TTL           | `QAPI_GLITCHTIP_PROJECTS_CACHE_TTL`               | `3600`  | Cache TTL for projects (seconds)     |
| Alerts cache TTL             | `QAPI_GLITCHTIP_ALERTS_CACHE_TTL`                 | `3600`  | Cache TTL for project alerts (seconds)|

## Client Integration

**File:** `reconcile/glitchtip_project_alerts_api/integration.py`

**CLI Command:** `qontract-reconcile glitchtip-project-alerts-api`

**Arguments and Options:**

- `--instance`: Filter reconciliation to a specific Glitchtip instance by name

**Client Architecture:**

1. Queries `glitchtip_instances_v1` to get all configured Glitchtip instances
2. Queries `glitchtip_projects_v1` to get all projects with their alert configurations
3. Groups projects by instance name
4. For each instance (filtered by `--instance` if provided):
   - Reads the Glitchtip-Jira-Bridge token from Vault (if configured)
   - Builds the desired state per organization and project:
     - Resolves webhook URL secrets from Vault
     - Builds Jira webhook alerts (direct project or via escalation policy channels)
     - Validates alert name uniqueness and webhook URL uniqueness
5. Posts the complete desired state to `POST /reconcile`
6. Polls `GET /reconcile/{task_id}?timeout=300` for the result
7. Logs all computed actions and exits with code 1 on errors or timeout

## Troubleshooting

**Common Issues:**

**Issue 1: Organization or project not found**

- **Symptom:** Warning log `Organization '<name>' not found in instance '<instance>', skipping` or `Project '<slug>' not found in org '<org>', skipping`
- **Cause:** The organization or project exists in App-Interface desired state but has not been created in Glitchtip yet
- **Solution:** Create the organization/project in Glitchtip manually or via the `glitchtip` integration before alerts can be managed

**Issue 2: Task timeout**

- **Symptom:** `Glitchtip project alerts task did not complete within the timeout period` + exit code 1
- **Cause:** The Celery worker is slow or the Glitchtip API is unresponsive
- **Solution:** Check Celery worker health and Glitchtip API latency; the task may still complete in the background

**Issue 3: Duplicate webhook URL error**

- **Symptom:** `ValueError: Glitchtip project alert webhook URLs must be unique across a project`
- **Cause:** Two alerts within the same project share the same webhook URL
- **Solution:** Ensure each webhook recipient URL is unique within the project's alert definitions in App-Interface

**Issue 4: Reserved alert name**

- **Symptom:** `ValueError: 'Glitchtip-Jira-Bridge-Integration' alert name is reserved`
- **Cause:** An App-Interface alert definition uses the reserved Jira Bridge alert name
- **Solution:** Rename the alert in App-Interface to a different name

**Issue 5: Duplicate task skipped**

- **Symptom:** Task result shows `{"status": "skipped", "reason": "duplicate_task"}`
- **Cause:** A reconciliation for the same instances is already in progress
- **Solution:** Wait for the previous task to complete; this is expected behavior under concurrent runs

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/glitchtip_project_alerts/](../../qontract_api/qontract_api/integrations/glitchtip_project_alerts/)
- Client: [reconcile/glitchtip_project_alerts_api/integration.py](../../reconcile/glitchtip_project_alerts_api/integration.py)

**ADRs:**

- [ADR-003: Async-Only API with Blocking GET](../adr/ADR-003-async-only-api-with-blocking-get.md) — explains the POST/GET task pattern used by this integration
- [ADR-008: qontract-api Client Integration Pattern](../adr/ADR-008-qontract-api-client-integration-pattern.md) — overall client-server integration pattern
- [ADR-011: Dependency Injection Pattern](../adr/ADR-011-dependency-injection-pattern.md) — service/factory dependency injection
- [ADR-014: Three-Layer Architecture for External APIs](../adr/ADR-014-three-layer-architecture-for-external-apis.md) — GlitchtipWorkspaceClient caching layer
- [ADR-017: Factory Pattern](../adr/ADR-017-factory-pattern.md) — GlitchtipClientFactory

**External:**

- [Glitchtip Documentation](https://glitchtip.com/documentation)
- [Glitchtip API Reference](https://glitchtip.com/api)
