# LDAP Groups Integration

**Last Updated:** 2026-10-19

## Description

Manages Internal Groups (LDAP/Rover) group membership and metadata from App-Interface roles. The `ldap-groups-api` integration reconciles desired groups against the Internal Groups API via qontract-api. Client-side S3 state tracks `managed_groups` because the API cannot list all groups.

## Architecture

**Client (`reconcile/ldap_groups_api/`):**

- Loads roles and settings from App-Interface GraphQL
- Builds desired `Group` objects (role LDAP groups and AWS SSO groups)
- Loads `managed_groups` from S3 state
- POSTs desired state + managed names to qontract-api
- Persists `updated_managed_groups` to S3 when the task result includes a bookmark (`null` means unavailable, e.g. dedup skip or Celery failure without a reconcile result; `[]` is a confirmed empty managed set). Partial applies with a real bookmark still persist before the integration raises on errors
- On bookmark persist, writes `state/ldap-groups-api/managed_groups` and mirrors `state/ldap-groups/managed_groups` for legacy rollback
- Persists `pending_task` (`id`, `status_url`, `submitted_at`) before polling; the next run recovers that task before submitting again. Recovery uses a non-blocking status probe, then a blocking poll only if still pending. References older than **6 hours** (or missing `submitted_at`) are cleared as lost Celery ids; `managed_groups` is left unchanged. Within 6 hours, a blocking poll **408** leaves `pending_task` in place (task may still be running). qontract-api logs when Celery reports bare `PENDING` (unknown vs in-flight is not distinguishable until Celery 5.7+ `exists()`).

### Rollback to legacy `ldap-groups`

1. If S3 state has `pending_task`, run `ldap-groups-api` once (production, not dry-run) and wait until that task finishes and `pending_task` is cleared (or confirm the task failed and recovery completed). If recovery loops on a lost Celery task id, delete the `pending_task` object under `state/ldap-groups-api/` in the integration S3 bucket as an emergency step, then re-run.
2. Stop `ldap-groups-api`.
3. Enable `ldap-groups` (reads `state/ldap-groups/managed_groups`, kept in sync by the API client).
4. Do not run both jobs long term.

**Server (`qontract_api/integrations/ldap_groups/`):**

- Fetches current groups by name via Internal Groups API (Layer 2 workspace client)
- Diffs desired vs current with `diff_iterables`
- Creates, updates, or deletes groups
- Returns actions and `updated_managed_groups`

## API Endpoints

### Queue reconciliation

```http
POST /api/v1/integrations/ldap-groups/reconcile
Authorization: Bearer <JWT_TOKEN>
```

**Request body (abbreviated):**

```json
{
  "connection": {
    "secret_manager_url": "https://vault.example.com",
    "path": "app-sre/creds/internal-groups",
    "api_url": "https://groups.example.com",
    "issuer_url": "https://sso.example.com",
    "client_id": "client-id"
  },
  "desired_groups": [],
  "managed_group_names": ["existing-group"],
  "dry_run": true
}
```

**Response:** `202 Accepted` with `id`, `status`, and `status_url`.

### Task status

```http
GET /api/v1/integrations/ldap-groups/reconcile/{task_id}
Authorization: Bearer <JWT_TOKEN>
```

Returns `LdapGroupsTaskResult` including `updated_managed_groups`.

## CLI

```bash
qontract-reconcile ldap-groups-api --aws-sso-namespace it-cloud-aws
```

Legacy integration: `ldap-groups` (unchanged).

## Related

- Layer 1 client: `qontract_utils/internal_groups_api/`
- Legacy reference: `reconcile/ldap_groups/integration.py` (not modified per ADR-007)
