# Slack Usergroups Integration

**Last Updated:** 2025-11-26

## Description

This integration manages Slack usergroups across multiple workspaces (Slack instances) by reconciling desired state from app-interface with current state in Slack. It supports Slack Usergroup management based on roles, schedules, git repository ownership, and PagerDuty on-call rotations. The integration uses a client-server architecture where GraphQL queries happen client-side and reconciliation logic runs server-side via qontract-api.

## Features

- Create and manage Slack usergroups across multiple workspaces
- Automatically sync usergroup members from multiple sources:
  - app-interface roles and permissions
  - Time-based on-call schedules (with active time window filtering)
  - Git repository OWNERS files (GitHub/GitLab)
  - PagerDuty schedules and escalation policies
  - Cluster access roles (automatic cluster-specific usergroups)
- Update usergroup metadata (description, default channels)
- Whitelist-based management (only reconciles explicitly managed usergroups)
- Distributed caching and rate limiting for all external API calls
- RedHat users don't need an app-interface user file (`/access/user-1.yml`) anymore

## Desired State Details

The desired state for Slack usergroup membership is compiled from **five different sources**, each with specific inclusion conditions. All sources are combined using set union logic (no duplicates), and the final user list is sorted alphabetically.

### User Sources

#### 1. App-interface SlackUsergroups Permissions (`/access/permission-1.yml.roles`)

Users are included from permissions.roles if:

- User is in `role.users` list
- Role is not expired (filtered via `expiration.filter()`)

#### 2. App-interface Time-Based On-Call Schedules (`/app-sre/schedule-1.yml`)

Users are included from schedules if:

- User is in `schedule.schedule[].users` list
- Current time is within the schedule window: `start <= NOW <= end`
- Date format: "YYYY-MM-DD HH:MM" (UTC timezone)

#### 3. Git Repository OWNERS Files (`/access/permission-1.yml.ownersFromRepos`)

Users are included from git OWNERS files if:

-
- Repository URL is provided (format: `https://github.com/org/repo` or `https://github.com/org/repo:branch`)
- User is listed in `/OWNERS` file (`approvers` or `reviewers` lists)
- User exists in app-interface and the profile has `github_username` field set (user mapping)
- User has `tag_on_merge_requests != false` (default: true)

**API Endpoint:** `/api/v1/external/vcs-repo-owners`

#### 4. PagerDuty Schedules & Escalation Policies (`/access/permission-1.yml.pagerduty`)

Users are included from PagerDuty if:

- **Via Schedule ID** (`pagerduty.scheduleID`): Currently on-call users
- **Via Escalation Policy ID** (`pagerduty.escalationPolicyID`): Users in the escalation policy
- User mapping: PagerDuty email address must be in format `org_username@domain`

**API Endpoints:**

- `/api/v1/external/pagerduty-schedule-users`
- `/api/v1/external/pagerduty-escalation-policy-users`

#### 5. Cluster Access (Automatic Cluster Usergroups)

**Automatic Generation:** No explicit permission needed - generated from cluster access roles

**Usergroup Naming:** `{cluster-name}-cluster` (e.g., `app-sre-prod-01-cluster`)

Users are included if they have access to the cluster through roles with cluster or namespace access.

**User Inclusion Logic (Hierarchical Override):**

1. **User-level setting** (highest priority):
   - If `user.tag_on_cluster_updates` is defined (true/false): Use this value
   - If undefined: Fall back to role-level setting
2. **Role-level setting**:
   - If `role.tag_on_cluster_updates = false`: Skip entire role
   - If `role.tag_on_cluster_updates = true` or undefined: Include users (respecting user-level override)

**Cluster Access Requirements:**

A role provides cluster access if it has access to either:

**A) Namespace Access:**

- `access.namespace` is defined
- `namespace.managed_roles = true`
- `namespace.delete != true` (not marked for deletion)

**B) Cluster Access:**

- `access.cluster` is defined, AND
- `access.group` is defined (cluster group membership)

### User Validation & Filtering

After compiling users from all sources, the following validation and filtering occurs:

**Client-Side (reconcile/slack_usergroups_api.py):**

- Only users with `org_username` field are included
- For PagerDuty, RedHat users no longer require an app-interface user file (`/access/user-*.yml`)
- GitHub username mapping for OWNERS files requires `user.github_username` field
- `tag_on_merge_requests` filtering for git OWNERS (default: true)
- `tag_on_cluster_updates` filtering for cluster usergroups (default: true)

**Server-Side (qontract_api):**

- Email format: `{org_username}@redhat.com`
- All non-existent users (not in Slack workspace) are filtered out
- All non-existent channels (not in Slack workspace) are filtered out

## Architecture

**Client-Side ([reconcile/slack_usergroups_api.py](../../reconcile/slack_usergroups_api.py)):**

- Fetches desired state:
  - from app-interface (GraphQL) permissions, users, clusters, and roles
  - from qontract-api external endpoints (VCS repo owners, PagerDuty)
- Compiles usergroup membership from multiple sources:
  - Roles (with expiration filtering)
  - Time-based schedules (filters by active time windows)
  - Git OWNERS files (via qontract-api external endpoints)
  - PagerDuty schedules and escalation policies (via qontract-api)
  - Cluster access roles (generates cluster-specific usergroups)
- Transforms data to API request format
- Calls qontract-api reconciliation endpoint
- Processes and logs results (actions, errors)

**Server-Side (qontract_api/integrations/slack_usergroups/):**

- Fetches current state from Slack API (users, usergroups, channels)
- Computes diff between desired and current state (using differ utility)
- Generates reconciliation actions (create, update_users, update_metadata)
- Executes actions (if not dry-run) with rate limiting
- Uses multi-tier caching (memory + Redis) with distributed locking
- Provides cache updates instead of invalidation (O(1) performance)

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/slack-usergroups/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "workspaces": [
    {
      "name": "app-sre",
      "vault_token_path": "app-sre/integrations-output/slack-workspace-1/slack-api-token",
      "usergroups": [
        {
          "handle": "oncall-team",
          "config": {
            "description": "On-call team members",
            "users": ["user1", "user2"],
            "channels": ["team-alerts", "general"]
          }
        }
      ],
      "managed_usergroups": ["oncall-team", "dev-team"]
    }
  ],
  "dry_run": true
}
```

**Response:** (202 Accepted)

```json
{
  "task_id": "temp-1732562400000",
  "status": "pending",
  "status_url": "/api/v1/integrations/slack-usergroups/reconcile/temp-1732562400000"
}
```

### Get Task Result

```http
GET /api/v1/integrations/slack-usergroups/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: 60, max: 300)

**Response:**

```json
{
  "status": "success",
  "actions": [
    {
      "action_type": "update_users",
      "workspace": "app-sre",
      "usergroup": "oncall-team",
      "users": ["user1", "user2"],
      "users_to_add": ["user2"],
      "users_to_remove": ["user3"]
    }
  ],
  "applied_count": 0,
  "errors": null
}
```

### Models

**Request Fields:**

| Field        | Type                   | Required | Default | Description                                                                                |
| ------------ | ---------------------- | -------- | ------- | ------------------------------------------------------------------------------------------ |
| `workspaces` | `list[SlackWorkspace]` | Yes      | -       | List of Slack workspaces with their usergroups                                             |
| `dry_run`    | `bool`                 | No       | `true`  | If true, only calculate actions without executing (CRITICAL: defaults to true for safety!) |

**SlackWorkspace Fields:**

| Field                | Type                   | Required | Description                                                           |
| -------------------- | ---------------------- | -------- | --------------------------------------------------------------------- |
| `name`               | `string`               | Yes      | Workspace name (unique identifier)                                    |
| `vault_token_path`   | `string`               | Yes      | Vault path to Slack workspace token                                   |
| `usergroups`         | `list[SlackUsergroup]` | Yes      | List of usergroups with their desired configuration                   |
| `managed_usergroups` | `list[string]`         | Yes      | Whitelist of usergroup handles managed by this integration (SECURITY) |

**SlackUsergroup Fields:**

| Field    | Type                   | Required | Description                                 |
| -------- | ---------------------- | -------- | ------------------------------------------- |
| `handle` | `string`               | Yes      | Usergroup handle/name (e.g., "oncall-team") |
| `config` | `SlackUsergroupConfig` | Yes      | Usergroup configuration                     |

**SlackUsergroupConfig Fields:**

| Field         | Type           | Required | Description                                    |
| ------------- | -------------- | -------- | ---------------------------------------------- |
| `description` | `string`       | No       | Usergroup description                          |
| `users`       | `list[string]` | No       | Sorted list of user emails                     |
| `channels`    | `list[string]` | No       | Sorted list of channel names (e.g., "general") |

**Validation Rules:**

- `users` and `channels` lists are automatically sorted (validated via Pydantic)
- Usergroup handles must be in `managed_usergroups` whitelist (security check)
- Empty users list is allowed (Slack uses dummy deleted user internally)

**Response Fields:**

| Field           | Type                   | Description                                                     |
| --------------- | ---------------------- | --------------------------------------------------------------- |
| `status`        | `TaskStatus`           | Task execution status (pending/success/failed)                  |
| `actions`       | `list[Action]`         | List of actions calculated/performed                            |
| `applied_count` | `int`                  | Number of actions actually applied (0 if dry_run=True)          |
| `errors`        | `list[string] \| None` | List of errors encountered during reconciliation (null if none) |

The integration can perform these reconciliation actions:

`create`:

**Description:** Create a new usergroup in the workspace

**Fields:**

- `action_type`: `"create"` (literal)
- `workspace`: Workspace name
- `usergroup`: Usergroup handle/name
- `users`: List of users to add (sorted)
- `description`: Usergroup description

**Example:**

```json
{
  "action_type": "create",
  "workspace": "app-sre",
  "usergroup": "new-team",
  "users": ["user1", "user2"],
  "description": "New team usergroup"
}
```

`update_users`:

**Description:** Update usergroup membership (add/remove users)

**Fields:**

- `action_type`: `"update_users"` (literal)
- `workspace`: Workspace name
- `usergroup`: Usergroup handle/name
- `users`: Complete list of users after update (sorted)
- `users_to_add`: Users being added (for logging)
- `users_to_remove`: Users being removed (for logging)

**Example:**

```json
{
  "action_type": "update_users",
  "workspace": "app-sre",
  "usergroup": "oncall-team",
  "users": ["user1", "user2"],
  "users_to_add": ["user2"],
  "users_to_remove": ["user3"]
}
```

`update_metadata`:

**Description:** Update usergroup metadata (description and/or default channels)

**Fields:**

- `action_type`: `"update_metadata"` (literal)
- `workspace`: Workspace name
- `usergroup`: Usergroup handle/name
- `description`: Updated description
- `channels`: Updated list of channel names (sorted)

**Example:**

```json
{
  "action_type": "update_metadata",
  "workspace": "app-sre",
  "usergroup": "oncall-team",
  "description": "Updated description",
  "channels": ["alerts", "general"]
}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` - must explicitly set to `false` to apply changes
- Whitelist-based management via `managed_usergroups` (only listed usergroups are reconciled)
- Usergroups not in whitelist are never modified (orphan protection)
- Validation errors prevent reconciliation if usergroup not in whitelist

**Managed Resources:**

- Only usergroups listed in `managed_usergroups` are reconciled
- Usergroups not in desired state are NOT deleted (orphan protection)
- Empty user lists use dummy deleted user (Slack API constraint - usergroups cannot be empty)

**Rate Limiting:**

- Token bucket rate limiter per workspace
- Configurable via environment variables:
  - `QAPI_SLACK__RATE_LIMIT_TIER`: Slack tier (tier1-tier4, default: tier2)
  - `QAPI_SLACK__RATE_LIMIT_TOKENS`: Bucket capacity (default: 20)
  - `QAPI_SLACK__RATE_LIMIT_REFILL_RATE`: Tokens per second (default: 1.0)
- Rate limit applies to all Slack API calls (enforced via pre-hooks)
- Distributed rate limiting using Redis backend

**Caching:**

- Multi-tier caching (in-memory + Redis) for Slack data
- Cache keys: `slack:<workspace>:users`, `slack:<workspace>:usergroups`, `slack:<workspace>:channels`
- TTLs (configurable):
  - Users cache: 12 hours
  - Usergroups cache: 1 hour
  - Channels cache: 12 hours

**Task Execution:**

- Task timeout: Configurable via `timeout` query parameter (max: 300 seconds)
- Default timeout: 60 seconds (configurable via `QAPI_API_TASK_DEFAULT_TIMEOUT`)
- Maximum timeout: 300 seconds (configurable via `QAPI_API_TASK_MAX_TIMEOUT`)
- Blocking GET with timeout to retrieve results

**Other Constraints:**

- Usergroups cannot have zero users (Slack API limitation - uses dummy deleted user)
- User emails must match Slack workspace users (non-existent users are filtered out), e.g. `<org-username>@redhat.com`

## Required Components

**Vault Secrets:**

- `<vault_token_path>`: Slack API token for each workspace (e.g., `app-sre/integrations-output/slack-workspace-1/slack-api-token`)
  - Scopes required: `usergroups:read`, `usergroups:write`, `users:read`, `channels:read`

**External APIs:**

- Slack API (Web API)
  - Base URL: `https://slack.com/api/`
  - Authentication: Bearer token (from Vault)
  - Documentation: <https://api.slack.com/web>
  - Methods used: `users.list`, `usergroups.list`, `usergroups.create`, `usergroups.update`, `usergroups.users.update`, `conversations.list`
- PagerDuty API (via qontract-api external endpoints)
  - For fetching on-call users from schedules/escalation policies
- GitHub/GitLab API (via qontract-api external endpoints)
  - For fetching OWNERS file contributors

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `slack:<workspace>:<resource_type>`
- Distributed locks: `lock:slack:<workspace>:<resource_type>`
- TTLs: Configurable per resource type (see environment variables)

## Configuration

**app-interface Schema:**

The integration uses GraphQL queries to fetch desired state from app-interface. Key schema fields include:

- **Permissions** (`PermissionSlackUsergroupV1`):
  - `workspace`: Slack workspace reference
  - `handle`: Usergroup handle/name
  - `description`: Usergroup description
  - `channels`: Default channels for usergroup
  - `roles`: Roles whose users should be in the usergroup
  - `schedule`: Time-based on-call schedule
  - `owners_from_repos`: Git repository URLs to fetch OWNERS from
  - `pagerduty`: PagerDuty schedule/escalation policy references
  - `skip`: Boolean to skip this permission

- **Workspace** (from permission):
  - `name`: Workspace name
  - `managed_usergroups`: Whitelist of managed usergroup handles
  - `integrations`: Integration configurations (token path, default channel)

- **Users** (`UserV1`):
  - `org_username`: Organization username
  - `github_username`: GitHub username (for OWNERS mapping)
  - `tag_on_merge_requests`: Whether to tag user
  - `tag_on_cluster_updates`: Whether user should be in cluster usergroups

- **Clusters** (`ClusterV1`):
  - Generates cluster-specific usergroups (e.g., `<cluster-name>-cluster`)
  - Based on cluster access roles

- **Roles** (`RoleV1`):
  - `users`: List of users in role
  - `tag_on_cluster_updates`: Whether role members should be in cluster usergroups
  - `access`: Cluster/namespace access definitions

**Integration Settings:**

| Setting              | Environment Variable                 | Default  | Description                         |
| -------------------- | ------------------------------------ | -------- | ----------------------------------- |
| API Timeout          | `QAPI_SLACK__API_TIMEOUT`            | `30`     | Slack API call timeout (seconds)    |
| Max Retries          | `QAPI_SLACK__API_MAX_RETRIES`        | `3`      | Max retry attempts for failed calls |
| Rate Limit Tier      | `QAPI_SLACK__RATE_LIMIT_TIER`        | `tier2`  | Slack API tier (tier1-tier4)        |
| Rate Limit Tokens    | `QAPI_SLACK__RATE_LIMIT_TOKENS`      | `20`     | Token bucket capacity               |
| Rate Limit Refill    | `QAPI_SLACK__RATE_LIMIT_REFILL_RATE` | `1.0`    | Tokens per second refill rate       |
| Users Cache TTL      | `QAPI_SLACK__USERS_CACHE_TTL`        | 12 hours | Users cache TTL (seconds)           |
| Usergroups Cache TTL | `QAPI_SLACK__USERGROUP_CACHE_TTL`    | 1 hour   | Usergroups cache TTL (seconds)      |
| Channels Cache TTL   | `QAPI_SLACK__CHANNELS_CACHE_TTL`     | 12 hours | Channels cache TTL (seconds)        |
| Task Max Timeout     | `QAPI_API_TASK_MAX_TIMEOUT`          | `300`    | Maximum blocking timeout (seconds)  |
| Task Default Timeout | `QAPI_API_TASK_DEFAULT_TIMEOUT`      | `60`     | Default timeout if not specified    |

## Client Integration

**File:** [reconcile/slack_usergroups_api.py](../../reconcile/slack_usergroups_api.py)

**CLI Command:** `qontract-reconcile slack-usergroups-api`

**Arguments and Options:**

- `--workspace-name`: Filter by Slack workspace name
- `--usergroup-name`: Filter by specific usergroup handle

**Client Architecture:**

1. Fetch desired state from app-interface GraphQL API
2. Compile usergroup membership from multiple sources:
   - Permissions roles
   - Time-based schedules (filtered by active time window)
   - Git OWNERS files (via qontract-api `/api/v1/external/vcs-repo-owners`)
   - PagerDuty schedules/policies (via qontract-api `/api/v1/external/pagerduty-*`)
   - Cluster access roles
3. Build `SlackWorkspace` objects with usergroups
4. POST to `/reconcile` endpoint (queue task)
5. GET from `/reconcile/{task_id}` with timeout (blocking mode)
6. Log actions and errors

## Troubleshooting

**Common Issues:**

**Issue 1: Usergroup not in managed_usergroups**

- **Symptom:** `KeyError: usergroup X not in managed usergroups`
- **Cause:** Trying to manage usergroup not whitelisted in workspace configuration
- **Solution:** Add usergroup handle to `managed_usergroups` list in app-interface workspace configuration

**Issue 2: Task timeout**

- **Symptom:** `408 Request Timeout: Task still pending after N seconds`
- **Cause:** Reconciliation takes longer than timeout value
- **Solution:** Increase timeout parameter in GET request:

  ```bash
  curl -X GET "http://localhost:8000/.../reconcile/{task_id}?timeout=300"
  ```

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/slack_usergroups/](../../qontract_api/qontract_api/integrations/slack_usergroups/)
  - [models.py](../../qontract_api/qontract_api/integrations/slack_usergroups/models.py) - Pydantic models for API
  - [service.py](../../qontract_api/qontract_api/integrations/slack_usergroups/service.py) - Reconciliation business logic
  - [router.py](../../qontract_api/qontract_api/integrations/slack_usergroups/router.py) - FastAPI endpoints
  - [slack_workspace_client.py](../../qontract_api/qontract_api/integrations/slack_usergroups/slack_workspace_client.py) - Caching + compute layer
  - [slack_factory.py](../../qontract_api/qontract_api/integrations/slack_usergroups/slack_factory.py) - Client factory with rate limiting
- Client: [reconcile/slack_usergroups_api.py](../../reconcile/slack_usergroups_api.py)

**External:**

- [Slack Web API Documentation](https://api.slack.com/web)
- [Slack Usergroups API](https://api.slack.com/methods#usergroups)
- [PagerDuty API Documentation](https://developer.pagerduty.com/api-reference/)
