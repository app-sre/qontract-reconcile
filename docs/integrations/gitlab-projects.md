# GitLab Projects Integration

**Last Updated:** 2026-09-28

## Description

The `gitlab-projects-api` integration creates GitLab projects declared in App-Interface under configured GitLab instances/groups.

Every requested project is cross-validated against App-Interface `codeComponents`.

## Features

- Creates GitLab projects that are declared (via `projectRequests`) but don't yet exist in the target group
- Cross-validates every requested project against App-Interface `codeComponents` before sending desired state to the server — fails the entire run if any project has no matching codeComponent, so misconfigurations are caught before merge instead of silently dropped
- Never deletes projects — a project that exists in GitLab but is no longer requested is left untouched
- Supports targeted debug runs via `--instance-name` and `--project-name` CLI filters
- Deduplicates concurrent reconciliation runs for the same set of instances

## Desired State Details

Desired state comes from two independent App-Interface GraphQL sources:

1. **`gitlabinstance_v1`** — declares GitLab instances, each with a `url`, `sslVerify`, a Vault `token` reference, and a list of `projectRequests` (`group` + `projects` names)
2. **`apps_v1.codeComponents`** — each app declares its repos as codeComponents with a `url`

Every `(group, project)` pair from `projectRequests` is reconstructed into a full repo URL (`{instance.url}/{group}/{project}`) and matched by exact string against the set of declared codeComponent URLs. A project with no matching codeComponent causes the entire run to fail with an `IntegrationError` listing every offending project — a deliberate fail-fast, since the server-side reconciliation never learns about codeComponents or apps at all, so a misconfigured `projectRequests` entry must be caught and fixed in App-Interface before the desired state is ever sent to qontract-api.

**Example app-interface config:**

```yaml
# data/dependencies/gitlab/gitlab.yml
$schema: /dependencies/gitlab-instance-1.yml
name: gitlab-cee
url: https://gitlab.cee.redhat.com
sslVerify: false
token:
  path: app-sre/ci-int/gitlab-token
  field: gitlab-token
projectRequests:
- group: service
  projects:
  - my-plain-project
```

```yaml
# data/services/my-app/app.yml
codeComponents:
- name: my-plain-project
  url: https://gitlab.cee.redhat.com/service/my-plain-project
```

## Architecture

**Client-Side (`reconcile/gitlab_projects_api.py`):**

- Queries `gitlabinstance_v1` and `apps_v1.codeComponents` from App-Interface using qenerate-generated types
- Optionally narrows instances/projects to `--instance-name`/`--project-name` filters for targeted debug runs
- Cross-validates every requested project against declared codeComponents, and raises `IntegrationError` if any project has no match
- Builds `GitlabInstanceConfig` per instance with a Vault `Secret` reference (path/field/version) - no token values leave the client
- Sends the complete desired state to qontract-api in a single request

**Server-Side (`qontract_api/integrations/gitlab_projects/`):**

- Fetches each group's current project list from GitLab via `GitlabWorkspaceClient` (Layer 2 — cached)
- Computes the diff using `qontract_utils.differ.diff_iterables`: only creates are ever generated, deletions are deliberately never actioned
- Executes actions per group (if not dry-run), isolating errors per action and per group/instance

## API Endpoints

Follows the standard async-only pattern (ADR-003): `POST /api/v1/integrations/gitlab-projects/reconcile` queues a task and returns `202` with a `status_url`; `GET /api/v1/integrations/gitlab-projects/reconcile/{task_id}` retrieves the result, optionally blocking via `?timeout=N`. See Models below for the request/response shape.

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
          "projects": ["my-plain-project"]
        }
      ]
    }
  ],
  "dry_run": true
}
```

### Models

**Request Fields:**

| Field       | Type                         | Required | Default | Description                                       |
| ----------- | ---------------------------- | -------- | ------- | -------------------------------------------------- |
| `instances` | `list[GitlabInstanceConfig]` | Yes      | -       | Desired GitLab instance/group/project state        |
| `dry_run`   | `bool`                       | No       | `true`  | If true, only calculate actions without executing  |

**GitlabInstanceConfig Fields:**

| Field        | Type                      | Required | Description                                       |
| ------------ | ------------------------- | -------- | -------------------------------------------------- |
| `name`       | `string`                  | Yes      | GitLab instance name                               |
| `url`        | `string`                  | Yes      | GitLab instance URL                                |
| `ssl_verify` | `bool`                    | No       | Whether to verify SSL certificates (default `true`)|
| `token`      | `Secret`                  | Yes      | Vault reference for the instance token             |
| `groups`     | `list[GitlabGroupConfig]` | No       | Desired group/project state                        |

**GitlabGroupConfig Fields:**

| Field      | Type        | Required | Description                                              |
| ---------- | ----------- | -------- | --------------------------------------------------------- |
| `group`    | `string`    | Yes      | GitLab group full path                                    |
| `projects` | `list[str]` | No       | Desired project names under this group (must be unique)   |

**Validation Rules:**

- Project names must be unique within a group (`GitlabGroupConfig` rejects duplicates)

**Response Fields:**

| Field             | Type                        | Description                                             |
| ----------------- | --------------------------- | -------------------------------------------------------- |
| `status`          | `TaskStatus`                | Task execution status (pending/success/failed)           |
| `actions`         | `list[GitlabProjectAction]` | All actions calculated (desired − current)                |
| `applied_count`   | `int`                       | Number of actions actually applied (0 if dry_run=True)    |
| `applied_actions` | `list[GitlabProjectAction]` | Actions successfully applied (non-dry-run only)            |
| `errors`          | `list[string]`              | Errors encountered during reconciliation                  |

The integration can perform these reconciliation actions:

`create`:

**Description:** Create a new, empty project.

**Fields:** `instance`, `group`, `project_name`

**Example:**

```json
{
  "action_type": "create",
  "instance": "gitlab-cee",
  "group": "service",
  "project_name": "my-plain-project"
}
```

## Limits and Constraints


**Managed Resources:**

- Only projects declared via `projectRequests` **and** matched by a codeComponent URL are considered desired state
- Existing projects not in desired state are left untouched (no orphan cleanup)

**Caching:**

- Each group's project list is cached per GitLab instance: `gitlab:{url}:group:{group}:projects`
- TTL: configurable via `QAPI_GITLAB_PROJECTS__GROUP_PROJECTS_CACHE_TTL` (default: 11 minutes)

**Events:**

- One CloudEvent published per applied action: `qontract-api.gitlab-projects.<action_type>`
- One CloudEvent published per error: `qontract-api.gitlab-projects.error`

## Required Components

**Vault Secrets:**

- `<token.path>`: GitLab instance API token (per instance, declared in App-Interface)

**External APIs:**

- GitLab API (v4, via [python-gitlab](https://python-gitlab.readthedocs.io/))
  - Base URL: per-instance `url` (e.g. `https://gitlab.cee.redhat.com`)
  - Authentication: private token (`private_token`)
  - Client: `qontract_utils.gitlab_api.GitlabApi` for group listing/project creation

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `gitlab:{url}:group:{group}:projects`
- TTL: 660 seconds / 11 minutes (default)

## Configuration

**App-Interface Schema:**

```yaml
# gitlabinstance_v1 entry
$schema: /dependencies/gitlab-instance-1.yml
name: gitlab-cee
url: https://gitlab.cee.redhat.com
sslVerify: false
token:
  path: app-sre/ci-int/gitlab-token
  field: gitlab-token
projectRequests:
- group: service
  projects:
  - my-project
```

**Integration Settings:**

| Setting                      | Environment Variable                             | Default | Description                           |
| ----------------------------- | ------------------------------------------------- | ------- | -------------------------------------- |
| GitLab API timeout             | `QAPI_GITLAB_PROJECTS__API_TIMEOUT`               | `30`    | GitLab API request timeout in seconds  |
| Group project list cache TTL   | `QAPI_GITLAB_PROJECTS__GROUP_PROJECTS_CACHE_TTL`  | `660`   | Cache TTL in seconds (11 minutes)      |

## Client Integration

**File:** `reconcile/gitlab_projects_api.py`

**CLI Command:** `qontract-reconcile gitlab-projects-api`

**Arguments and Options:**

- `--instance-name`: Reconcile just this GitLab instance
- `--project-name`: Reconcile just this project (repeatable, e.g. `--project-name foo --project-name bar`)

**Client Architecture:**

- Builds desired state entirely from GraphQL before calling qontract-api, including the codeComponent cross-reference validation
- Passes Vault `Secret` *references* (path + field + version) — no token values in the request body

## Troubleshooting

**Missing codeComponent**

- **Symptom:** `IntegrationError: gitlab-projects-api: N project(s) missing from codeComponents: <url>, ...`
- **Cause:** A `projectRequests` entry declares a project with no matching `codeComponents` entry (or the URL doesn't exactly match, e.g. a trailing slash mismatch)
- **Solution:** Add the missing codeComponent to the owning app in App-Interface, or remove the project from `projectRequests`

**Duplicate project names**

- **Symptom:** `ValidationError: duplicate project names: <name>`
- **Cause:** The same project name appears twice under one group's `projectRequests`
- **Solution:** Remove the duplicate entry

**Task timeout in dry-run**

- **Symptom:** `IntegrationError: gitlab-projects-api: task did not complete within the timeout period`
- **Cause:** Worker is overloaded or Celery task queue is backed up
- **Solution:** Check worker health and Celery queue depth; retry the run

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/gitlab_projects/](../../qontract_api/qontract_api/integrations/gitlab_projects/)
- Client: [reconcile/gitlab_projects_api.py](../../reconcile/gitlab_projects_api.py)
- Layer 1 (administration): [qontract_utils/qontract_utils/gitlab_api/](../../qontract_utils/qontract_utils/gitlab_api/)

**External:**

- [python-gitlab Documentation](https://python-gitlab.readthedocs.io/)
- [GitLab REST API Documentation](https://docs.gitlab.com/ee/api/)
