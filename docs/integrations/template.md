# Integration Documentation Template

This template provides a standardized format for documenting qontract-api integrations.

---

**Last Updated:** YYYY-MM-DD

## Description

[Brief 2-3 sentence description of what this integration does and what external system it manages]

## Features

- [Feature 1 - what the integration can do]
- [Feature 2]
- [Feature 3]
- ...

## Desired State Details

[Describe how the desired state is represented in App-Interface for this integration. Include details about relevant GraphQL schema fields, relationships, and any important constraints or conventions.]

## Architecture

**Client-Side (reconcile/<name>_api.py):**

- Fetches desired state from App-Interface (GraphQL)
- Transforms data to API request format
- Calls qontract-api reconciliation endpoint
- Processes and logs results

**Server-Side (qontract_api/integrations/<name>/):**

- Fetches current state from [External System/API]
- Computes diff between desired and current state
- Generates reconciliation actions
- Executes actions (if not dry-run)

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/<name>/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "field1": "description of field1",
  "field2": "description of field2",
  "dry_run": true
}
```

**Response:** (202 Accepted)

```json
{
  "task_id": "uuid-string",
  "status": "pending",
  "status_url": "/api/v1/integrations/<name>/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/<name>/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: None = immediate status)

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

| Field     | Type           | Required | Default | Description                                       |
| --------- | -------------- | -------- | ------- | ------------------------------------------------- |
| `field1`  | `string`       | Yes      | -       | Description of field1                             |
| `field2`  | `list[string]` | Yes      | -       | Description of field2                             |
| `dry_run` | `bool`         | No       | `true`  | If true, only calculate actions without executing |

**Validation Rules:**

- [List any validation rules, e.g., "users must be sorted"]
- [e.g., "workspace names must be unique"]

**Response Fields:**

| Field           | Type                   | Description                                            |
| --------------- | ---------------------- | ------------------------------------------------------ |
| `status`        | `TaskStatus`           | Task execution status (pending/success/failed)         |
| `actions`       | `list[Action]`         | List of actions calculated/performed                   |
| `applied_count` | `int`                  | Number of actions actually applied (0 if dry_run=True) |
| `errors`        | `list[string] \| None` | List of errors encountered during reconciliation       |

The integration can perform these reconciliation actions:

`action_type_1`:

**Description:** [What this action does]

**Fields:**

- `workspace`: Workspace name
- `resource`: Resource identifier
- [Additional fields]

**Example:**

```json
{
  "action_type": "action_type_1",
  "workspace": "example",
  "resource": "resource-name",
  "field": "value"
}
```

`action_type_2`:

[Repeat for each action type]

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` - must explicitly set to `false` to apply changes
- [Other safety features]

**Managed Resources:**

- [e.g., "Only usergroups listed in managed_usergroups are reconciled"]
- [e.g., "Resources not in desired state are NOT deleted (orphan protection)"]

**Rate Limiting:**

- [External API rate limits]
- [Token bucket settings if applicable]

**Caching:**

- [What is cached and for how long]
- [Cache keys and TTLs]

**Other Constraints:**

- [Any other important limitations]

## Required Components

**Vault Secrets:**

- `path/to/secret`: Description of secret (e.g., API token)

**External APIs:**

- [External System] API (version X.Y)
  - Base URL: `https://api.example.com`
  - Authentication: [Bearer token | OAuth | etc.]
  - Documentation: [Link to API docs]

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `prefix:key:pattern`
- TTL: X seconds

## Configuration

**App-Interface Schema:**

[Describe the GraphQL schema fields needed in app-interface]

```yaml
# Example YAML configuration
$schema: /path/to/schema.yml
name: example
field1: value1
field2:
  - item1
  - item2
```

**Integration Settings:**

| Setting   | Environment Variable | Default | Description |
| --------- | -------------------- | ------- | ----------- |
| Setting 1 | `QAPI_SETTING_1`     | `value` | Description |
| Setting 2 | `QAPI_SETTING_2`     | `value` | Description |

## Client Integration

**File:** `reconcile/<name>_api.py`

**CLI Command:** `qontract-reconcile <name>-api`

**Arguments and Options:**

- `--resource-name`: Filter by resource name
- `--workspace-name`: Filter by workspace
- [Other filters]

**Client Architecture:**

- [All relevant details about client-side processing]

## Troubleshooting

**Common Issues:**

**Issue 1: [Description]**

- **Symptom:** [What you see]
- **Cause:** [Why it happens]
- **Solution:** [How to fix]

**Issue 2: [Description]**

- **Symptom:** [What you see]
- **Cause:** [Why it happens]
- **Solution:** [How to fix]

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/<name>/](../qontract_api/integrations/<name>/)
- Client: [reconcile/<name>_api.py](../../reconcile/<name>_api.py)

**External:**

- [External API Documentation]
- [Related Tools/Services]
