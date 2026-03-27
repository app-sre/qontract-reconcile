# Glitchtip

**Last Updated:** 2026-03-27

## Description

The `glitchtip-api` integration manages [Glitchtip](https://glitchtip.com/) organizations, teams, projects, and users across multiple instances. It reconciles the full desired state defined in App-Interface against the current state in each Glitchtip instance, creating, updating, or deleting resources as needed. Team membership is enriched from both App-Interface roles and LDAP groups via qontract-api's LDAP external endpoint.

## Features

- Manage organizations across multiple Glitchtip instances
- Manage teams within organizations, including full membership reconciliation
- Manage projects (name, platform, event throttle rate) and their team associations
- Manage organization-level user membership and roles (invite, update role, delete)
- Enrich team members from LDAP groups via qontract-api's LDAP external endpoint
- Multi-instance reconciliation in a single API call
- Dry-run mode enabled by default for safe planning before applying changes
- Deduplication of concurrent reconciliation tasks per instance set

## Desired State Details

The desired state is defined in App-Interface through two GraphQL types:

- **`glitchtip_instances_v1`**: Glitchtip instance configuration (console URL, automation token, automation user email, timeouts, mail domain)
- **`glitchtip_projects_v1`**: Per-project configuration including platform, teams (with roles and LDAP groups), and the owning organization

Each project belongs to an organization, which belongs to an instance. The client builds the full hierarchy (`instance → organization → [users, teams, projects]`) before sending it to the API.

**User membership:** Organization users are derived from the union of all team members within that organization. Team members come from:
1. **App-Interface roles** (`glitchtip_team.roles`): Users attached to roles that have `glitchtip_roles` for the organization. The role name from `glitchtip_roles[].role` is used; if no organization-specific role is defined, `member` is used.
2. **LDAP groups** (`glitchtip_team.ldap_groups`): Member IDs fetched from InternalGroups via qontract-api; role defaults to `member` or the value in `membersOrganizationRole`. Roles from App-Interface roles take precedence over LDAP roles.

**Project slug:** Uses `project_id` from App-Interface if set; otherwise derived by slugifying the project name (Django-compatible: lowercase, spaces/hyphens merged, special characters removed).

**Automation user:** The automation user email is excluded from all user diffs to prevent the reconciler from removing itself.

**Reconciliation ordering** (preserved from the legacy `glitchtip` integration):
1. Create missing organizations — for new orgs, all child actions (users, teams, team memberships, projects) are generated upfront in the same pass (single-pass convergence), so dry-run shows the full picture and no extra API calls are made
2. Reconcile users (invite / delete / update role) — must precede team membership (existing orgs only)
3. Reconcile teams (create / delete) and team memberships (existing orgs only)
4. Reconcile projects (create / update / delete) and project-team associations (existing orgs only)
5. Delete obsolete organizations (last)

## Architecture

**Client-Side (`reconcile/glitchtip_api/integration.py`):**

- Fetches all Glitchtip instances from App-Interface (`glitchtip_instances_v1`)
- Fetches all Glitchtip projects from App-Interface (`glitchtip_projects_v1`), grouped by instance and organization
- Fetches LDAP settings directly from App-Interface (`ldap_groups_settings_v1`) and resolves OAuth2 credentials from Vault; fails fast if `api_url`, `issuer_url`, or `client_id` are missing
- Collects all unique LDAP groups across all teams, then pre-fetches them concurrently via `asyncio.gather` to the qontract-api LDAP external endpoint (`GET /api/v1/external/ldap/groups/{group_name}/members`), avoiding duplicate calls when the same group appears in multiple teams
- Builds complete desired state hierarchy and sends it to qontract-api via `POST /reconcile`
- In dry-run mode, polls `GET /reconcile/{task_id}` with a 300-second timeout and logs all actions
- Exits with code 1 if errors occurred

**Server-Side (`qontract_api/integrations/glitchtip/`):**

- Retrieves Glitchtip API tokens and automation user email from the configured secret manager (Vault)
- Fetches current state from Glitchtip (organizations, users, teams, projects) via `GlitchtipWorkspaceClient`
- Computes diff between current and desired state for each resource type
- Generates ordered reconciliation actions (14 action types)
- Executes actions against the Glitchtip API (if `dry_run=False`)
- Returns a structured result with all actions, applied count, and any errors

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/glitchtip/reconcile
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
        "path": "secret/glitchtip/token",
        "field": "token"
      },
      "automation_user_email": {
        "secret_manager_url": "https://vault.example.com",
        "path": "secret/glitchtip/automation",
        "field": "email"
      },
      "read_timeout": 30,
      "max_retries": 3,
      "organizations": [
        {
          "name": "my-org",
          "teams": [
            {
              "name": "my-team",
              "users": [
                {"email": "user@example.com", "role": "member"}
              ]
            }
          ],
          "projects": [
            {
              "name": "my-project",
              "slug": "my-project",
              "platform": "python",
              "event_throttle_rate": 0,
              "teams": ["my-team"]
            }
          ],
          "users": [
            {"email": "user@example.com", "role": "member"}
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
  "status_url": "/api/v1/integrations/glitchtip/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/glitchtip/reconcile/{task_id}?timeout=30
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

**Request Fields — `GlitchtipReconcileRequest`:**

| Field       | Type              | Required | Default | Description                                       |
| ----------- | ----------------- | -------- | ------- | ------------------------------------------------- |
| `instances` | `list[GIInstance]` | Yes     | -       | List of Glitchtip instances with desired state    |
| `dry_run`   | `bool`            | No       | `true`  | If true, only calculate actions without executing |

**`GIInstance` Fields:**

| Field                   | Type                   | Required | Default | Description                                       |
| ----------------------- | ---------------------- | -------- | ------- | ------------------------------------------------- |
| `name`                  | `string`               | Yes      | -       | Unique instance identifier                        |
| `console_url`           | `string`               | Yes      | -       | Glitchtip base URL                                |
| `token`                 | `Secret`               | Yes      | -       | Vault secret reference for API Bearer token       |
| `automation_user_email` | `Secret`               | Yes      | -       | Vault secret reference for automation user email  |
| `read_timeout`          | `int`                  | No       | `30`    | HTTP read timeout in seconds                      |
| `max_retries`           | `int`                  | No       | `3`     | Maximum HTTP retries                              |
| `organizations`         | `list[GIOrganization]` | No       | `[]`    | Desired organizations                             |

**`GIOrganization` Fields:**

| Field      | Type                  | Required | Default | Description                          |
| ---------- | --------------------- | -------- | ------- | ------------------------------------ |
| `name`     | `string`              | Yes      | -       | Organization name                    |
| `teams`    | `list[GlitchtipTeam]` | No       | `[]`    | Desired teams                        |
| `projects` | `list[GIProject]`     | No       | `[]`    | Desired projects                     |
| `users`    | `list[GlitchtipUser]` | No       | `[]`    | Desired organization-level members   |

**`GIProject` Fields:**

| Field                | Type           | Required | Default | Description                              |
| -------------------- | -------------- | -------- | ------- | ---------------------------------------- |
| `name`               | `string`       | Yes      | -       | Project display name                     |
| `slug`               | `string`       | Yes      | -       | URL-friendly identifier                  |
| `platform`           | `string\|null` | No       | `null`  | Project platform (e.g., `python`, `js`)  |
| `event_throttle_rate`| `int`          | No       | `0`     | Event throttle rate (0 = no throttle)    |
| `teams`              | `list[string]` | No       | `[]`    | Team slugs this project belongs to       |

**`GlitchtipTeam` Fields:**

| Field   | Type                  | Required | Default | Description                       |
| ------- | --------------------- | -------- | ------- | --------------------------------- |
| `name`  | `string`              | Yes      | -       | Team name (slug is auto-derived)  |
| `users` | `list[GlitchtipUser]` | No       | `[]`    | Desired team members              |

**`GlitchtipUser` Fields:**

| Field   | Type     | Required | Default    | Description                   |
| ------- | -------- | -------- | ---------- | ----------------------------- |
| `email` | `string` | Yes      | -          | User email address            |
| `role`  | `string` | No       | `"member"` | Organization role             |

**Response Fields:**

| Field           | Type                   | Description                                            |
| --------------- | ---------------------- | ------------------------------------------------------ |
| `status`        | `TaskStatus`           | Task execution status (pending/success/failed)         |
| `actions`       | `list[GlitchtipAction]`| List of actions calculated/performed                   |
| `applied_count` | `int`                  | Number of actions actually applied (0 if dry_run=True) |
| `errors`        | `list[string] \| None` | List of errors encountered during reconciliation       |

The integration can perform these 14 reconciliation actions:

---

`create_organization`:

**Description:** Create a new organization in the Glitchtip instance.

**Fields:**
- `organization`: Organization name

**Example:**
```json
{"action_type": "create_organization", "organization": "my-org"}
```

---

`delete_organization`:

**Description:** Delete an organization that is no longer in the desired state. Executed last, after all per-org reconciliation.

**Fields:**
- `organization`: Organization name

**Example:**
```json
{"action_type": "delete_organization", "organization": "old-org"}
```

---

`invite_user`:

**Description:** Invite a user to an organization with the specified role.

**Fields:**
- `organization`: Organization name
- `email`: User email address
- `role`: Organization role (e.g., `member`, `admin`)

**Example:**
```json
{"action_type": "invite_user", "organization": "my-org", "email": "user@example.com", "role": "member"}
```

---

`delete_user`:

**Description:** Remove a user from an organization. The automation user email is never deleted.

**Fields:**
- `organization`: Organization name
- `email`: User email address

**Example:**
```json
{"action_type": "delete_user", "organization": "my-org", "email": "user@example.com"}
```

---

`update_user_role`:

**Description:** Change a user's organization-level role.

**Fields:**
- `organization`: Organization name
- `email`: User email address
- `role`: New role

**Example:**
```json
{"action_type": "update_user_role", "organization": "my-org", "email": "user@example.com", "role": "admin"}
```

---

`create_team`:

**Description:** Create a new team in an organization.

**Fields:**
- `organization`: Organization name
- `team_slug`: Team slug (derived from team name using Django slugify)

**Example:**
```json
{"action_type": "create_team", "organization": "my-org", "team_slug": "platform-team"}
```

---

`delete_team`:

**Description:** Delete a team that is no longer in the desired state.

**Fields:**
- `organization`: Organization name
- `team_slug`: Team slug

**Example:**
```json
{"action_type": "delete_team", "organization": "my-org", "team_slug": "old-team"}
```

---

`add_user_to_team`:

**Description:** Add an existing organization member to a team.

**Fields:**
- `organization`: Organization name
- `team_slug`: Team slug
- `email`: User email address

**Example:**
```json
{"action_type": "add_user_to_team", "organization": "my-org", "team_slug": "platform-team", "email": "user@example.com"}
```

---

`remove_user_from_team`:

**Description:** Remove a user from a team (does not remove them from the organization).

**Fields:**
- `organization`: Organization name
- `team_slug`: Team slug
- `email`: User email address

**Example:**
```json
{"action_type": "remove_user_from_team", "organization": "my-org", "team_slug": "platform-team", "email": "user@example.com"}
```

---

`create_project`:

**Description:** Create a new project in an organization, assigned to the first team in the desired project's team list. Additional team associations and non-zero event throttle rates are applied immediately after creation.

**Fields:**
- `organization`: Organization name
- `project_name`: Project display name

**Example:**
```json
{"action_type": "create_project", "organization": "my-org", "project_name": "my-service"}
```

---

`update_project`:

**Description:** Update a project's platform or event throttle rate when they differ from desired state.

**Fields:**
- `organization`: Organization name
- `project_slug`: Project slug

**Example:**
```json
{"action_type": "update_project", "organization": "my-org", "project_slug": "my-service"}
```

---

`delete_project`:

**Description:** Delete a project that is no longer in the desired state.

**Fields:**
- `organization`: Organization name
- `project_slug`: Project slug

**Example:**
```json
{"action_type": "delete_project", "organization": "my-org", "project_slug": "old-service"}
```

---

`add_project_to_team`:

**Description:** Associate a project with a team.

**Fields:**
- `organization`: Organization name
- `project_slug`: Project slug
- `team_slug`: Team slug

**Example:**
```json
{"action_type": "add_project_to_team", "organization": "my-org", "project_slug": "my-service", "team_slug": "platform-team"}
```

---

`remove_project_from_team`:

**Description:** Disassociate a project from a team.

**Fields:**
- `organization`: Organization name
- `project_slug`: Project slug
- `team_slug`: Team slug

**Example:**
```json
{"action_type": "remove_project_from_team", "organization": "my-org", "project_slug": "my-service", "team_slug": "old-team"}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- The automation user email is never deleted from any organization
- Projects cannot be created without at least one team — the creation is skipped with a warning if no teams are defined
- Organizations are deleted last, after all per-org user/team/project reconciliation is complete
- For new organizations, all child actions (users, teams, team memberships, projects) are generated upfront — no API calls to the Glitchtip instance are needed during calculation
- For new teams within existing organizations, team membership is seeded during execution (not pre-calculated), since the team slug must exist in Glitchtip before members can be added

**Managed Resources:**

- All organizations listed in the desired state are managed; organizations not in the desired state are deleted
- Only users derived from App-Interface roles and LDAP groups are in the desired state; extra users are removed (except the automation user)
- Teams not in the desired state are deleted; projects not in the desired state are deleted

**Rate Limiting:**

- Configurable `read_timeout` (default: 30s) and `max_retries` (default: 3) per instance

**Caching:**

- `GlitchtipWorkspaceClient` uses a two-tier cache (memory + Redis) for all read operations
- Cache is invalidated after each mutation (create/update/delete)
- Cache keys: `glitchtip:{instance_name}:organizations`, `glitchtip:{instance_name}:org:{org_slug}:users`, `glitchtip:{instance_name}:org:{org_slug}:teams`, `glitchtip:{instance_name}:org:{org_slug}:projects`

**Other Constraints:**

- Team slugs are derived from team names using Django slugify convention (lowercase, spaces/hyphens merged, special characters stripped)
- Project slugs use `projectId` from App-Interface if set; otherwise derived by slugifying the project name
- The Celery task has a 600-second lock timeout for deduplication

## Required Components

**Vault Secrets (per Glitchtip instance):**

- `<automation_token.path>`: Glitchtip Bearer API token for the automation user
- `<automation_user_email.path>`: Automation user email address (excluded from user diffs)

**LDAP (InternalGroups) credentials** (from App-Interface `ldap_groups_settings`):

- `api_url`: InternalGroups API base URL
- `issuer_url`: OAuth2 token endpoint
- `client_id`: OAuth2 client ID
- `client_secret`: OAuth2 client secret (path stored in App-Interface, value fetched at runtime per LDAP group request)

**External APIs:**

- Glitchtip REST API
  - Base URL: configured per instance via `console_url`
  - Authentication: Bearer token
- InternalGroups (LDAP) API — accessed via qontract-api LDAP external endpoint
  - Authentication: OAuth2 client credentials (fetched per-request via secret manager)

**Cache Backend:**

- Redis/Valkey connection required for task deduplication and workspace client caching

## Configuration

**App-Interface Schema:**

```yaml
# glitchtip_instances_v1
$schema: /app-sre/glitchtip/instance-1.yml
name: my-glitchtip
description: "My Glitchtip instance"
consoleUrl: https://glitchtip.example.com
automationToken:
  path: app-sre/glitchtip/automation-token
  field: token
automationUserEmail:
  path: app-sre/glitchtip/automation-token
  field: email
readTimeout: 30
maxRetries: 3
mailDomain: example.com
```

```yaml
# glitchtip_projects_v1
$schema: /app-sre/glitchtip/project-1.yml
name: my-service
platform: python
projectId: my-service          # optional; slug if not set
eventThrottleRate: 100          # optional; 0 if not set
teams:
  - name: platform-team
    roles:
      - $ref: /teams/platform-eng.yml
    ldapGroups:
      - platform-engineers
    membersOrganizationRole: member   # role for LDAP members; default: member
organization:
  name: my-org
  instance:
    $ref: /app-sre/glitchtip/instance.yml
```

**Integration Settings:**

| Setting                | Environment Variable          | Default | Description                               |
| ---------------------- | ----------------------------- | ------- | ----------------------------------------- |
| `api_task_max_timeout` | `QAPI_TASK_MAX_TIMEOUT`       | —       | Maximum GET timeout in seconds (enforced) |
| `api_task_default_timeout` | `QAPI_TASK_DEFAULT_TIMEOUT`| —       | Default GET timeout if not specified      |

## Client Integration

**File:** `reconcile/glitchtip_api/integration.py`

**CLI Command:** `qontract-reconcile glitchtip-api`

**Arguments and Options:**

- `--instance`: Filter reconciliation to a single Glitchtip instance by name (optional)

**Client Architecture:**

- Queries all Glitchtip instances (`glitchtip_instances_v1`) and projects (`glitchtip_projects_v1`) from App-Interface via GraphQL
- Reads LDAP settings from App-Interface (`ldap_groups_settings_v1`) and validates that `api_url`, `issuer_url`, and `client_id` are present in Vault before proceeding
- Groups projects by instance name, then by organization name
- Collects all unique LDAP groups across all teams, pre-fetches them concurrently via `asyncio.gather`, and passes the cache to team-user resolution (avoids duplicate API calls for shared groups)
- Merges LDAP members with role-based users (role-based takes precedence for the same email)
- Builds the full `GIInstance → GIOrganization → [GlitchtipTeam, GIProject, GlitchtipUser]` structure
- Submits the reconciliation request to qontract-api
- In dry-run mode: polls task status with 300s timeout, logs each action, exits with code 1 on errors

## Troubleshooting

**Common Issues:**

**Issue 1: Project creation skipped with warning**

- **Symptom:** Log warning `"Cannot create project without a team"`, project not created
- **Cause:** A project in the desired state has an empty `teams` list
- **Solution:** Ensure every project in App-Interface has at least one team defined in its `glitchtip_teams` list

**Issue 2: LDAP members not appearing in teams**

- **Symptom:** Team users are empty or only role-based users appear
- **Cause:** LDAP credentials are misconfigured, or the group name is incorrect
- **Solution:** Verify `ldap_groups_settings.credentials` in App-Interface contains valid `api_url`, `issuer_url`, `client_id`, and `client_secret`; confirm the LDAP group name exists in InternalGroups

**Issue 3: Automation user getting reconciled**

- **Symptom:** `invite_user` or `delete_user` action appears for the automation user
- **Cause:** The `automation_user_email` secret is returning the wrong value or is misconfigured
- **Solution:** Verify the Vault path and field for `automationUserEmail` on the Glitchtip instance

**Issue 4: Task times out in dry-run**

- **Symptom:** Log error `"Glitchtip task did not complete within the timeout period"`, exit code 1
- **Cause:** Reconciliation of a large Glitchtip instance takes longer than 300 seconds
- **Solution:** Check qontract-api Celery worker health; consider filtering by `--instance` to reduce scope

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/glitchtip/](../qontract_api/integrations/glitchtip/)
- Client: [reconcile/glitchtip_api/integration.py](../../reconcile/glitchtip_api/integration.py)
- Domain Models: [qontract_api/qontract_api/integrations/glitchtip/domain.py](../qontract_api/integrations/glitchtip/domain.py)
- GQL Definitions: [reconcile/gql_definitions/glitchtip/](../../reconcile/gql_definitions/glitchtip/)

**External:**

- [Glitchtip Documentation](https://glitchtip.com/documentation)
- [InternalGroups / LDAP external endpoint](../qontract_api/external/ldap/)
