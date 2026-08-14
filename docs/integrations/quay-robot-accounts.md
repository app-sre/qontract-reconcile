# quay-robot-accounts

**Last Updated:** 2026-08-14

## Description

Manages Quay organization robot accounts from app-interface desired state. Creates and updates robots, reconciles team membership and repository permissions, and deletes robots only when explicitly marked with `delete: true`.

This is a **CLI integration** (`reconcile/quay_robot_accounts.py`). It is not yet migrated to the qontract-api client/server pattern.

## Features

- Create robot accounts that are defined in app-interface but missing in Quay
- Delete robot accounts only when `delete: true` is set on the datafile
- Reconcile team membership for teams listed in the org's `managedTeams`
- Reconcile repository permissions (`read` / `write` / `admin`) when the org has `managedRepos: true`
- Org opt-in via `managedRobotAccounts: true` — orgs without the flag are not inventoried
- Desired-only inventory — only Quay orgs referenced by robot datafiles are queried
- Fail closed on auth errors (401/403) for opted-in orgs (no soft-skip / Slack warning spam)

## Desired State Details

Robots are defined in app-interface with schema `/access/quay-robot-1.yml` and queried via GraphQL (`quay_robots_v1`). Each robot has:

- `name`: Robot short name (appears in Quay as `<org>+<name>`)
- `description`: Optional description
- `quay_org`: Crossref to `/dependencies/quay-org-1.yml` (must include `automationToken` and `managedRobotAccounts: true`)
- `teams`: Optional list of team names (each must be in the org's `managedTeams`)
- `repositories`: Optional list of `{name, permission}` grants (requires org `managedRepos: true`)
- `delete`: When `true`, delete the robot if it exists

Robots present in Quay but absent from app-interface are **not** deleted.

## Architecture

**Pattern:** Legacy CLI reconciliation (plan-and-apply) using the shared Quay API store.

```text
reconcile/quay_robot_accounts.py
    │
    ├── GraphQL ──────────────→ app-interface (quay_robots_v1)
    │
    ├── get_quay_api_store() ─→ Quay orgs + automation tokens (QUAY_ORGS_QUERY)
    │
    ├── validate_desired_state → managedRobotAccounts / managedTeams / managedRepos
    │
    ├── list_robot_accounts ──→ Quay API (desired orgs only)
    │
    ├── calculate_diff ───────→ create / delete / team / repo actions
    │
    └── apply_action ─────────→ Quay API (skipped when dry_run=True)
```

**Module (`reconcile/quay_robot_accounts.py`):**

- Fetches desired robots from App-Interface (GraphQL)
- Validates org opt-in and team/repo guardrails
- Fetches current robots only for validated desired orgs
- Builds current state only for robots present in desired state
- Computes diff and applies actions (unless dry-run)

**Shared Quay store (`reconcile/quay_base.py`):**

- Loads org automation tokens, `managedTeams`, `managedRepos`, `managedRobotAccounts`
- Shared with `quay-membership`, `quay-repos`, `quay-permissions`, and Quay mirror integrations

## API Endpoints

Not applicable — this integration does not expose qontract-api HTTP endpoints. Reconciliation runs in-process via the CLI.

### Models

**Desired robot fields (from GraphQL / schema):**

| Field | Type | Required | Default | Description |
| ----- | ---- | -------- | ------- | ----------- |
| `name` | `string` | Yes | - | Robot short name |
| `description` | `string \| None` | No | `None` | Robot description |
| `quay_org` | org crossref | Yes | - | Target Quay org |
| `teams` | `list[string]` | No | `[]` | Teams to join (`managedTeams` only) |
| `repositories` | `list[{name, permission}]` | No | `[]` | Repo permission grants |
| `delete` | `bool` | No | `false` | Explicit delete request |

**Validation Rules:**

- Org must exist in the Quay API store (automation token present)
- Org must have `managedRobotAccounts: true`
- Every desired team must be listed in the org's `managedTeams`
- Repository permissions require `managedRepos: true` on the org

The integration can perform these reconciliation actions:

`create`:

**Description:** Create a robot account in the Quay organization.

**Fields:**

- `robot_name`: Robot short name
- `org_name` / `instance_name`: Target org
- `description`: Optional description

`delete`:

**Description:** Delete a robot account (only when desired `delete: true`).

**Fields:**

- `robot_name`, `org_name`, `instance_name`

`add_team` / `remove_team`:

**Description:** Add or remove the robot from a managed team.

**Fields:**

- `robot_name`, `org_name`, `instance_name`, `team`

`set_repo_permission` / `remove_repo_permission`:

**Description:** Set or remove a robot's role on a repository.

**Fields:**

- `robot_name`, `org_name`, `instance_name`, `repo`, `permission` (for set)

## Limits and Constraints

**Safety:**

- CLI `--dry-run` / deploy `DRY_RUN` controls apply vs plan-only
- Robots not declared in app-interface are never deleted (orphan protection)
- Explicit `delete: true` is required to remove a managed robot

**Managed Resources:**

- Only orgs with `managedRobotAccounts: true` are reconciled
- Only teams in `managedTeams` are reconciled for membership
- Repository permissions are tracked only when `managedRepos: true`
- Inventory is limited to orgs/robots present in desired state

**Rate Limiting:**

- Uses the shared Quay API client; no integration-specific rate limiter

**Caching:**

- None (direct Quay API calls each run)

**Other Constraints:**

- Auth failures (401/403) on opted-in orgs fail the integration (exit non-zero)
- Robot tokens are **not** written to Vault; CI credentials remain a separate manual/Vault step

## Required Components

**Vault Secrets:**

- Per-org Quay `automationToken` referenced from `/dependencies/quay-org-1.yml` (Administer Organization; Administer Repositories if managing repo permissions)

**External APIs:**

- Quay.io (or self-hosted Quay) Organization / Robot Account APIs
  - Base URL: from Quay instance (`quay_org.instance.url`)
  - Authentication: org automation token from Vault
  - Documentation: [Quay API](https://docs.quay.io/api/)

**Cache Backend:**

- Not required

## Configuration

**App-Interface Schema:**

Org opt-in (`/dependencies/quay-org-1.yml`):

```yaml
$schema: /dependencies/quay-org-1.yml

labels: {}

name: my-team
description: Example Quay org
instance:
  $ref: /dependencies/quay/instance.yml
managedRepos: true
managedRobotAccounts: true
managedTeams:
- ci
automationToken:
  path: app-sre/creds/quay-org-my-team
  field: token
```

Robot definition (`/access/quay-robot-1.yml`):

```yaml
$schema: /access/quay-robot-1.yml

labels: {}

name: push
description: CI push robot

quay_org:
  $ref: /dependencies/quay/my-team.yml

teams:
- ci

repositories:
- name: frontend
  permission: write
```

**Integration Settings:**

| Setting | Environment Variable | Default | Description |
| ------- | -------------------- | ------- | ----------- |
| Dry run | `DRY_RUN` / `--dry-run` | deploy-dependent | Plan only when dry-run |

Deployed via `data/integrations/qontract-reconcile-quay-robot-accounts.yml` in app-interface.

## Client Integration

**File:** `reconcile/quay_robot_accounts.py`

**CLI Command:** `qontract-reconcile quay-robot-accounts`

**Arguments and Options:**

- Global `--dry-run` / `--no-dry-run`
- Global `--config` (qontract-server + Vault)

**Example:**

```bash
uv run qontract-reconcile --config config.toml --dry-run quay-robot-accounts
```

## Troubleshooting

**Issue 1: GraphQL rejects `managedRobotAccounts`**

- **Symptom:** `Cannot query field "managedRobotAccounts" on type "QuayOrg_v1"` on all Quay integrations
- **Cause:** Field missing from `graphql-schemas/schema.yml` (JSON schema alone is not enough) or schemas image not promoted
- **Solution:** Ensure both JSON and GraphQL schemas include the field, then promote `SCHEMAS_IMAGE_TAG`

**Issue 2: `managedRobotAccounts is not set to true`**

- **Symptom:** Integration exits with error for a desired robot's org
- **Cause:** Org datafile lacks `managedRobotAccounts: true`
- **Solution:** Add the opt-in flag to the Quay org definition (and ensure the automation token can manage robots)

**Issue 3: Team not a managedTeam**

- **Symptom:** Validation error naming a team
- **Cause:** Robot `teams` entry not listed in org `managedTeams`
- **Solution:** Add the team to `managedTeams`, or remove it from the robot definition

**Issue 4: Repo permissions with `managedRepos: false`**

- **Symptom:** Validation error about repository permissions
- **Cause:** Robot lists `repositories` but org has `managedRepos: false`
- **Solution:** Enable `managedRepos` or drop repository grants from the robot

## References

**Code:**

- Integration: [`reconcile/quay_robot_accounts.py`](../../reconcile/quay_robot_accounts.py)
- Quay API store: [`reconcile/quay_base.py`](../../reconcile/quay_base.py)
- GQL query: [`reconcile/gql_definitions/quay_robot_accounts/`](../../reconcile/gql_definitions/quay_robot_accounts/)
- Tests: [`reconcile/test/test_quay_robot_accounts.py`](../../reconcile/test/test_quay_robot_accounts.py)

**External:**

- Schema: [`/access/quay-robot-1.yml`](https://github.com/app-sre/qontract-schemas/blob/main/schemas/access/quay-robot-1.yml)
- Org schema: [`/dependencies/quay-org-1.yml`](https://github.com/app-sre/qontract-schemas/blob/main/schemas/dependencies/quay-org-1.yml)
- Usage docs (app-interface): [Quay Robot Accounts](https://gitlab.cee.redhat.com/service/app-interface/-/blob/master/docs/platform-users/ci-cd/quay-robot-accounts.md)
- Related CLI integrations: `quay-membership`, `quay-repos`, `quay-permissions`
