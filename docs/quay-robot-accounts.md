# quay-robot-accounts

CLI integration that reconciles Quay organization robot accounts from
app-interface desired state.

**Code:** [`reconcile/quay_robot_accounts.py`](../reconcile/quay_robot_accounts.py)
**Schema:** [`/access/quay-robot-1.yml`](https://github.com/app-sre/qontract-schemas/blob/main/schemas/access/quay-robot-1.yml)
**Usage (app-interface):** [Quay Robot Accounts](https://gitlab.cee.redhat.com/service/app-interface/-/blob/master/docs/platform-users/ci-cd/quay-robot-accounts.md) (platform-users CI/CD docs)

## What it manages

For each robot defined in app-interface:

- Create / delete the robot (delete only when `delete: true`)
- Team membership for teams listed in the org's `managedTeams`
- Repository permissions when the org has `managedRepos: true`

Robots that exist in Quay but are absent from app-interface are **not**
deleted. Explicit removal requires a datafile with `delete: true`.

## Org opt-in

The shared Quay org store (`get_quay_api_store` / `QUAY_ORGS_QUERY`) loads
every org with an automation token. This integration only inventories and
reconciles orgs that:

1. Appear in at least one desired robot definition, and
2. Have `managedRobotAccounts: true` on `/dependencies/quay-org-1.yml`

Orgs without the flag fail validation with an error (fail closed). Auth
failures (401/403) against an opted-in org also fail the run — there is
no soft-skip path.

## Flow

1. Fetch desired robots from GraphQL (`quay_robots_v1`)
2. Validate orgs (automation token, `managedRobotAccounts`, `managedTeams`,
   `managedRepos` when repos are set)
3. List robots only for validated desired orgs
4. Build current state only for robots present in desired state
5. Diff → create / delete / team / repo permission actions
6. Apply (unless `--dry-run`)

## Running locally

```bash
uv run qontract-reconcile --config config.toml --dry-run quay-robot-accounts
```

## Related integrations

- `quay-membership` — human/bot team membership (`managedTeams`)
- `quay-repos` / `quay-permissions` — repositories and permissions
  (`managedRepos`)
