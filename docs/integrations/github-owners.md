# GitHub Owners Integration

**Last Updated:** 2026-03-25

## Description

The `github-owners` integration ensures that GitHub organization admin (owner) membership reflects the desired state declared in App-Interface. It reads roles with `github-org` or `github-org-team` owner permissions and adds any missing users or bots to the corresponding GitHub organizations. Owner removal is intentionally not supported — removing org admins requires explicit manual review.

## Features

- Adds GitHub users and bots as org admins based on App-Interface role permissions
- Treats pending invitations as equivalent to existing membership (no duplicate invites)
- Filters expired roles automatically before computing desired state
- Supports GitHub Enterprise via configurable `base_url` per organization
- Dry-run mode calculates actions without touching GitHub
- Add-only semantics: owners are never automatically removed (safety by design)

## Desired State Details

Desired state is derived from `roles_v1` in App-Interface. A user or bot becomes a desired owner of a GitHub org when:

1. They are a member of a role that has a `PermissionGithubOrg_v1` or `PermissionGithubOrgTeam_v1` permission with `role: owner`
2. The role is not expired (no `expirationDate`, or `expirationDate` is in the future)
3. The user has a `github_username` set on their profile

The GitHub org's API token is looked up from the corresponding `githuborg_v1` entry in App-Interface.

**Example role with GitHub owner permission:**

```yaml
$schema: /access/role-1.yml
name: my-team-admins
permissions:
  - $schema: /access/permission-github-org-1.yml
    service: github-org
    org: my-github-org
    role: owner
users:
  - $ref: /teams/my-team/users/alice.yml
bots:
  - $ref: /bots/my-bot.yml
```

## Architecture

**Client-Side (`reconcile/github_owners_api.py`):**

- Queries `roles_v1` from App-Interface using qenerate-generated types (`reconcile/gql_definitions/github_owners_api/roles.py`)
- Filters expired roles via `expiration.filter()`
- Queries `githuborg_v1` for org token vault references
- Aggregates desired owners per org across all matching roles (union of all role members)
- Normalizes usernames to lowercase and sorts them deterministically
- Sends the complete desired state for all orgs to qontract-api in a single request
- In dry-run: waits for task completion and logs planned actions; raises `IntegrationError` on errors or timeout
- In non-dry-run: fire-and-forget (task completes asynchronously, events are published)

**Server-Side (`qontract_api/integrations/github_owners/`):**

- Resolves the GitHub API token from Vault via `SecretManager`
- Fetches current org admin members via PyGithub (`get_members(role="admin")`)
- Fetches pending invitations via direct GitHub REST API (PyGithub does not support this endpoint)
- Combines both sets as the "current" membership to avoid re-inviting already-invited users
- Computes diff using `diff_iterables()` — only the `add` set is used (no removals)
- Executes `add_member_as_admin` for each user in desired but not in current
- Publishes change events via the event framework for each successfully applied action

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/github-owners/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "organizations": [
    {
      "org_name": "my-github-org",
      "owners": ["alice", "bob"],
      "token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/creds/github",
        "field": "token",
        "version": 1
      },
      "base_url": "https://api.github.com"
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
  "status_url": "/api/v1/integrations/github-owners/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/github-owners/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: immediate status check)

**Response:**

```json
{
  "status": "success|failed|pending",
  "actions": [
    {
      "action_type": "add_owner",
      "org_name": "my-github-org",
      "username": "alice"
    }
  ],
  "applied_actions": [...],
  "applied_count": 1,
  "errors": []
}
```

### Models

**Request: `GithubOrgDesiredState` fields (per organization):**

| Field      | Type           | Required | Default                      | Description                                      |
| ---------- | -------------- | -------- | ---------------------------- | ------------------------------------------------ |
| `org_name` | `string`       | Yes      | -                            | GitHub organization name                         |
| `owners`   | `list[string]` | Yes      | -                            | Desired org admin usernames (lowercased, sorted) |
| `token`    | `Secret`       | Yes      | -                            | Vault secret reference for the GitHub API token  |
| `base_url` | `string`       | No       | `https://api.github.com`     | GitHub API base URL (override for GHE)           |
| `dry_run`  | `bool`         | No       | `true`                       | If true, only calculate actions without applying |

**Validation Rules:**

- `owners` are automatically lowercased and sorted by a field validator on `GithubOrgDesiredState`
- `base_url` defaults to `https://api.github.com`; override only for GitHub Enterprise

**Response Fields:**

| Field             | Type                   | Description                                                       |
| ----------------- | ---------------------- | ----------------------------------------------------------------- |
| `status`          | `TaskStatus`           | Task execution status (`pending`/`success`/`failed`)              |
| `actions`         | `list[GithubOwnerAction]` | All actions calculated (desired − current), including failed ones |
| `applied_actions` | `list[GithubOwnerAction]` | Actions that were successfully applied (non-dry-run only)         |
| `applied_count`   | `int`                  | Number of actions successfully applied (0 if `dry_run=true`)      |
| `errors`          | `list[string]`         | Errors encountered; task status is `failed` if non-empty          |

**Action Types:**

`add_owner`:

**Description:** Adds a user as an org admin (owner). This is the only action type — owner removal is intentionally not supported.

**Fields:**

- `action_type`: `"add_owner"` (literal)
- `org_name`: GitHub organization name
- `username`: GitHub username to add as org admin

**Example:**

```json
{
  "action_type": "add_owner",
  "org_name": "my-github-org",
  "username": "alice"
}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- **Owner removal is intentionally not supported.** Removing org admins is a high-impact operation requiring explicit manual review. The integration only ever adds owners.
- Pending invitations are treated as existing membership, preventing duplicate invitations

**Managed Resources:**

- Only organizations explicitly listed in the reconciliation request are processed
- Only the `add_owner` action is ever generated; existing owners not in desired state are left untouched

**Rate Limiting:**

- GitHub REST API rate limits apply; each org requires 2 API calls (admin members + pending invitations) plus one per add action
- PyGithub handles primary membership; raw `requests` are used for the invitations endpoint (not supported by PyGithub)

**Caching:**

- GitHub org members (admins + pending invitations) are cached per org
- Cache key: `github-org:{org_name}:members`
- TTL: `QAPI_GITHUB_ORG__MEMBERS_CACHE_TTL` (default: 3600 seconds / 1 hour)
- Cache is invalidated immediately after a successful `add_member_as_admin` call
- Two-tier caching: memory + Redis with distributed locking (double-check pattern)

**Other Constraints:**

- GitHub usernames are always normalized to lowercase before comparison and storage
- Task deduplication: concurrent reconciliations for the same org set are deduplicated (Celery lock, 10-minute timeout)

## Required Components

**Vault Secrets:**

- Per-org GitHub token path (configured in `githuborg_v1` in App-Interface, e.g., `app-sre/creds/github-<org-name>`): GitHub personal access token or app token with `admin:org` scope

**External APIs:**

- GitHub REST API v3
  - Base URL: `https://api.github.com` (configurable per org for GitHub Enterprise)
  - Authentication: Bearer token (`Authorization: token <TOKEN>`)
  - Required scopes: `admin:org` (for listing members and adding org admins)
  - Documentation: https://docs.github.com/en/rest/orgs/members

**Cache Backend:**

- Redis/Valkey connection required
- Cache keys: `github-org:{org_name}:members`
- TTL: 3600 seconds (configurable via `QAPI_GITHUB_ORG__MEMBERS_CACHE_TTL`)

## Configuration

**App-Interface Schema:**

Roles with GitHub org owner permissions are defined using `PermissionGithubOrg_v1` or `PermissionGithubOrgTeam_v1`:

```yaml
# Role granting GitHub org ownership
$schema: /access/role-1.yml
name: my-admins
permissions:
  - $schema: /access/permission-github-org-1.yml
    service: github-org
    org: my-github-org   # must match githuborg_v1 name
    role: owner
users:
  - $ref: /teams/.../users/alice.yml
```

GitHub org token is configured in `githuborg_v1`:

```yaml
$schema: /dependencies/github-org-1.yml
name: my-github-org
token:
  path: app-sre/creds/github-my-github-org
  field: token
  version: 1
```

**Integration Settings:**

| Setting                              | Environment Variable                     | Default | Description                                        |
| ------------------------------------ | ---------------------------------------- | ------- | -------------------------------------------------- |
| GitHub org members cache TTL         | `QAPI_GITHUB_ORG__MEMBERS_CACHE_TTL`     | `3600`  | Cache TTL in seconds for org admin + invitation lists |

## Client Integration

**File:** `reconcile/github_owners_api.py`

**CLI Command:** `qontract-reconcile github-owners-api`

**Arguments and Options:**

- `--org`: Filter reconciliation to a single GitHub organization name (optional; default: all orgs)

**Client Architecture:**

1. Queries `roles_v1` from App-Interface (GQL, using qenerate-generated types)
2. Filters expired roles using `expiration.filter()`
3. Queries `githuborg_v1` to get vault token references per org
4. Aggregates desired owners per org from all matching role+permission combinations
5. Sends one `POST /api/v1/integrations/github-owners/reconcile` request with the full desired state
6. In **dry-run**: polls `GET /reconcile/{task_id}` (blocking, 300s timeout), logs each `add_owner` action, raises `IntegrationError` on errors or timeout
7. In **non-dry-run**: returns immediately after queuing (fire-and-forget); applied actions are published as change events by the worker

**Example (dry-run via CLI):**

```bash
qd github-owners-api --dry-run

# Filter to one org
qd github-owners-api --org my-github-org --dry-run
```

**Example (direct API call):**

```bash
TOKEN=$(cd qontract_api && make generate-token SUBJECT=dev EXPIRES_DAYS=1 | tail -1)

curl -s -X POST http://localhost:8000/api/v1/integrations/github-owners/reconcile \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "organizations": [{
      "org_name": "my-github-org",
      "owners": ["alice", "bob"],
      "token": {
        "secret_manager_url": "https://vault.example.com",
        "path": "app-sre/creds/github-my-github-org",
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
- **Solution:** Set `QAPI_SECRETS__DEFAULT_PROVIDER_URL` and `QAPI_SECRETS__PROVIDERS` in the server's `.env` to include the vault URL, role ID, and secret ID

**Issue: `403 Forbidden` from GitHub API**

- **Symptom:** `add_member_as_admin` fails with HTTP 403
- **Cause:** The GitHub token in Vault does not have `admin:org` scope, or the token belongs to a non-owner
- **Solution:** Verify the token has `admin:org` scope and the authenticating user is an org owner

**Issue: User keeps getting re-invited every reconcile run**

- **Symptom:** `add_owner` action fires every run for the same user, but they never become a member
- **Cause:** The invitation may be expiring or being declined; or the user has no GitHub account matching the username
- **Solution:** Check GitHub org invitation status; confirm the `github_username` in App-Interface is correct and the user has accepted previous invitations

**Issue: Task times out in dry-run**

- **Symptom:** `IntegrationError: task did not complete within the timeout period`
- **Cause:** The Celery worker is overloaded or not running
- **Solution:** Check Celery worker health; increase timeout if needed (client-side `timeout=300` in `github_owners_task_status` call)

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/github_owners/](../../qontract_api/qontract_api/integrations/github_owners/)
- Client: [reconcile/github_owners_api.py](../../reconcile/github_owners_api.py)
- Layer 1 API client: [qontract_utils/qontract_utils/github_org/api.py](../../qontract_utils/qontract_utils/github_org/api.py)
- GQL definitions: [reconcile/gql_definitions/github_owners_api/](../../reconcile/gql_definitions/github_owners_api/)

**ADRs:**

- [ADR-002: Client-Side GraphQL](../adr/ADR-002-client-side-graphql.md)
- [ADR-003: Async-Only API with Blocking GET](../adr/ADR-003-async-only-api-with-blocking-get.md)
- [ADR-008: Integration Naming (_api suffix)](../adr/ADR-008-qontract-api-client-integration-pattern.md)
- [ADR-011: Dependency Injection](../adr/ADR-011-dependency-injection.md)
- [ADR-012: Pydantic Models](../adr/ADR-012-pydantic-models.md)
- [ADR-014: Three-Layer Architecture](../adr/ADR-014-three-layer-architecture.md)

**External:**

- [GitHub REST API — Organization Members](https://docs.github.com/en/rest/orgs/members)
- [GitHub REST API — Organization Invitations](https://docs.github.com/en/rest/orgs/members#list-pending-organization-invitations)
