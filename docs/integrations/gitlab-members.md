# GitLab Members Integration

**Last Updated:** 2026-11-03

## Description

The `gitlab-members` integration manages GitLab group membership declared in App-Interface, including on-call members resolved from PagerDuty schedules and escalation policies.

## Features

- Adds, removes, and updates the access level of GitLab group members to match the desired state declared in App-Interface
- Resolves desired members from app-interface roles (including `memberSources`-backed roles such as LDAP) and from PagerDuty on-call schedules/escalation policies
- When a user is granted access by multiple permissions for the same group, the highest access level wins
- Never deletes a member that's still part of any matching permission — only members absent from every permission for a group are removed
- PagerDuty lookups go through qontract-api's shared external PagerDuty endpoints (no direct PagerDuty API calls from the client)

## Desired State Details

Desired state comes from App-Interface's `permissions_v1` schema, specifically the `PermissionGitlabGroupMembership_v1` variant:

- `group`: the target GitLab group full path
- `access`: one of `owner` / `maintainer` / `developer` / `reporter` / `guest`
- `roles`: app-interface roles whose `users`/`bots` are granted `access` in `group` (roles may be backed by `memberSources`, e.g. LDAP groups)
- `pagerduty`: optional list of PagerDuty targets (`scheduleID` or `escalationPolicyID`) whose on-call users are granted `access` in `group`

There must be exactly one `gitlabinstance_v1` declared in App-Interface; its `managedGroups` list determines which groups are reconciled.

**Example app-interface config:**

```yaml
# data/dependencies/gitlab/gitlab.yml
$schema: /dependencies/gitlab-instance-1.yml
name: gitlab-cee
url: https://gitlab.cee.redhat.com
managedGroups:
- service
token:
  path: app-sre/ci-int/gitlab-token
  field: gitlab-token
```

```yaml
# data/permissions/service-gitlab-membership.yml
$schema: /access/permissions/gitlab-group-membership-1.yml
name: service-gitlab-membership
group: service
access: developer
roles:
- $ref: /teams/service-team/roles/service-team.yml
pagerduty:
- name: service-primary-oncall
  instance:
    $ref: /dependencies/pagerduty/redhat.yml
  scheduleID: PHS3079
```

## Architecture

**Client-Side (`reconcile/gitlab_members_api.py`):**

- Queries the single `gitlabinstance_v1` and its `GitlabGroupMembership` permissions, resolving role memberships (including `memberSources`) via `resolve_role_members`
- For each permission's PagerDuty targets, calls qontract-api's external PagerDuty endpoints (`pagerduty_schedule_users` / `pagerduty_escalation_policy_users`) and translates `pagerduty_username` to `org_username`
- Compiles desired membership per managed group (username → access level, highest wins across permissions)
- Sends the complete desired state to qontract-api in a single request

**Server-Side (`qontract_api/integrations/gitlab_members/`):**

- Fetches each group's current members from GitLab via `GitlabWorkspaceClient` (Layer 2 — cached), and resolves usernames to GitLab user IDs for additions
- Computes the diff using `qontract_utils.differ.diff_mappings`, keyed by username, comparing access level
- Executes add/remove/change-access actions per group (if not dry-run), isolating errors per action and per group/instance

## API Endpoints

Follows the standard async-only pattern (ADR-003): `POST /api/v1/integrations/gitlab-members/reconcile` queues a task and returns `202` with a `status_url`; `GET /api/v1/integrations/gitlab-members/reconcile/{task_id}` retrieves the result, optionally blocking via `?timeout=N`. See Models below for the request/response shape.

**Request Body:**

```json
{
  "instances": [
    {
      "name": "gitlab-cee",
      "url": "https://gitlab.cee.redhat.com",
      "ssl_verify": true,
      "token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/ci-int/gitlab-token",
        "field": "gitlab-token"
      },
      "groups": [
        {
          "group": "service",
          "members": [
            { "username": "jsmith", "access_level": 30 }
          ]
        }
      ]
    }
  ],
  "dry_run": true
}
```

### Models

**Request Fields:**

| Field       | Type                                | Required | Default | Description                                        |
| ----------- | ------------------------------------ | -------- | ------- | --------------------------------------------------- |
| `instances` | `list[GitlabMembersInstanceConfig]`  | Yes      | -       | Desired GitLab instance/group/membership state       |
| `dry_run`   | `bool`                                | No       | `true`  | If true, only calculate actions without executing    |

**GitlabMembersInstanceConfig Fields:**

| Field        | Type                              | Required | Description                                         |
| ------------ | ---------------------------------- | -------- | ----------------------------------------------------- |
| `name`       | `string`                           | Yes      | GitLab instance name                                  |
| `url`        | `string`                           | Yes      | GitLab instance URL                                   |
| `ssl_verify` | `bool`                             | No       | Whether to verify SSL certificates (default `true`)   |
| `token`      | `Secret`                           | Yes      | Vault reference for the instance token                |
| `groups`     | `list[GitlabMembersGroupConfig]`   | No       | Desired group membership state                        |

**GitlabMembersGroupConfig Fields:**

| Field     | Type                      | Required | Description                               |
| --------- | -------------------------- | -------- | ------------------------------------------- |
| `group`   | `string`                   | Yes      | GitLab group full path                      |
| `members` | `list[GitlabMemberConfig]` | No       | Desired members and their access levels     |

**GitlabMemberConfig Fields:**

| Field          | Type     | Required | Description                               |
| -------------- | -------- | -------- | -------------------------------------------- |
| `username`     | `string` | Yes      | GitLab username                              |
| `access_level` | `int`    | Yes      | Desired GitLab access level (10/20/30/40/50) |

**Response Fields:**

| Field             | Type                    | Description                                              |
| ----------------- | ------------------------ | ---------------------------------------------------------- |
| `status`          | `TaskStatus`             | Task execution status (pending/success/failed)              |
| `actions`         | `list[GitlabMemberAction]` | All actions calculated (desired − current)                |
| `applied_count`   | `int`                    | Number of actions actually applied (0 if dry_run=True)      |
| `applied_actions` | `list[GitlabMemberAction]` | Actions successfully applied (non-dry-run only)            |
| `errors`          | `list[string]`           | Errors encountered during reconciliation (e.g. unknown GitLab username) |

The integration can perform these reconciliation actions:

`add_member`:

**Description:** Add a user to a group at the given access level.

**Fields:** `instance`, `group`, `username`, `user_id`, `access_level`

**Example:**

```json
{
  "action_type": "add_member",
  "instance": "gitlab-cee",
  "group": "service",
  "username": "jsmith",
  "user_id": 42,
  "access_level": 30
}
```

`remove_member`:

**Description:** Remove a member from a group.

**Fields:** `instance`, `group`, `username`, `member_id`

**Example:**

```json
{
  "action_type": "remove_member",
  "instance": "gitlab-cee",
  "group": "service",
  "username": "jsmith",
  "member_id": 42
}
```

`change_access`:

**Description:** Change an existing member's access level.

**Fields:** `instance`, `group`, `username`, `member_id`, `access_level`

**Example:**

```json
{
  "action_type": "change_access",
  "instance": "gitlab-cee",
  "group": "service",
  "username": "jsmith",
  "member_id": 42,
  "access_level": 40
}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- A username desired for `add_member` that doesn't resolve to a GitLab user is reported as an error and skipped, rather than failing the whole group

**Managed Resources:**

- Only groups listed in the single `gitlabinstance_v1`'s `managedGroups` are reconciled
- A member only kept by one of several permissions for a group retains the highest access level across all matching permissions

**Caching:**

- Each group's member list is cached per GitLab instance: `gitlab:{url}:group:{group}:members`
- Username-to-user-ID lookups are cached per instance: `gitlab:{url}:user:{username}`
- TTL: configurable via `QAPI_GITLAB_PROJECTS__GROUP_MEMBERS_CACHE_TTL` (default: 5 minutes)

**Events:**

- One CloudEvent published per applied action: `qontract-api.gitlab-members.<action_type>`
- One CloudEvent published per error: `qontract-api.gitlab-members.error`

## Required Components

**Vault Secrets:**

- `<token.path>`: GitLab instance API token (declared in App-Interface)
- `<pagerduty.instance.token.path>`: PagerDuty API token per PagerDuty instance referenced by a permission (resolved server-side by the shared external PagerDuty endpoints)

**External APIs:**

- GitLab API (v4, via [python-gitlab](https://python-gitlab.readthedocs.io/))
  - Base URL: per-instance `url` (e.g. `https://gitlab.cee.redhat.com`)
  - Authentication: private token (`private_token`)
  - Client: `qontract_utils.gitlab_api.GitlabApi` for group member management
- PagerDuty REST API v2 (via the official [`pagerduty`](https://github.com/PagerDuty/pdpyras) client, Layer 1 `qontract_utils.pagerduty_api.PagerDutyApi`)
  - Accessed only through qontract-api's shared `/external/pagerduty/*` endpoints — the client never calls PagerDuty directly

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `gitlab:{url}:group:{group}:members`, `gitlab:{url}:user:{username}`
- TTL: 300 seconds / 5 minutes (default)

## Configuration

**App-Interface Schema:**

```yaml
# gitlabinstance_v1 entry
$schema: /dependencies/gitlab-instance-1.yml
name: gitlab-cee
url: https://gitlab.cee.redhat.com
managedGroups:
- service
token:
  path: app-sre/ci-int/gitlab-token
  field: gitlab-token
```

**Integration Settings:**

| Setting                       | Environment Variable                              | Default | Description                               |
| ------------------------------ | --------------------------------------------------- | ------- | -------------------------------------------- |
| GitLab API timeout             | `QAPI_GITLAB_PROJECTS__API_TIMEOUT`                 | `30`    | GitLab API request timeout in seconds         |
| Group members list cache TTL   | `QAPI_GITLAB_PROJECTS__GROUP_MEMBERS_CACHE_TTL`     | `300`   | Cache TTL in seconds (5 minutes)              |

## Client Integration

**File:** `reconcile/gitlab_members_api.py`

**CLI Command:** `qontract-reconcile gitlab-members-api`

**Arguments and Options:**

- None — the integration reconciles the single declared `gitlabinstance_v1` and all of its `managedGroups`

**Client Architecture:**

- Resolves role memberships (including `memberSources`) client-side via `resolve_role_members`, then enriches with PagerDuty on-call users via qontract-api's external PagerDuty endpoints
- Passes a Vault `Secret` *reference* (path + field + version) for the GitLab instance token — no token values in the request body

## Troubleshooting

**More than one GitLab instance**

- **Symptom:** `AppInterfaceSettingsError: More than one gitlab instance found!`
- **Cause:** More than one `gitlabinstance_v1` is declared in App-Interface
- **Solution:** This integration currently supports exactly one managed GitLab instance; remove or merge the extra instance

**GitLab user not found**

- **Symptom:** Task result contains an error like `<instance>/<group>/<username>: GitLab user not found`
- **Cause:** A desired username (from a role or PagerDuty on-call lookup) has no matching GitLab account
- **Solution:** Verify the username is correct, or that the user has signed into the GitLab instance at least once

**Task timeout in dry-run**

- **Symptom:** `IntegrationError: gitlab-members-api: task did not complete within the timeout period`
- **Cause:** Worker is overloaded or Celery task queue is backed up
- **Solution:** Check worker health and Celery queue depth; retry the run

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/gitlab_members/](../../qontract_api/qontract_api/integrations/gitlab_members/)
- Client: [reconcile/gitlab_members_api.py](../../reconcile/gitlab_members_api.py)
- Layer 1 (GitLab administration): [qontract_utils/qontract_utils/gitlab_api/](../../qontract_utils/qontract_utils/gitlab_api/)
- Layer 1 (PagerDuty): [qontract_utils/qontract_utils/pagerduty_api/](../../qontract_utils/qontract_utils/pagerduty_api/)

**External:**

- [python-gitlab Documentation](https://python-gitlab.readthedocs.io/)
- [GitLab REST API Documentation](https://docs.gitlab.com/ee/api/)
- [PagerDuty REST API v2 Documentation](https://developer.pagerduty.com/api-reference/)
