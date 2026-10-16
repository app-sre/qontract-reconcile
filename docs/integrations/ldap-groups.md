# LDAP Groups Integration

**Last Updated:** 2026-10-05

## Description

Manages Internal Groups (LDAP/Rover) group membership and metadata from App-Interface roles. The `ldap-groups-api` integration reconciles desired groups against the Internal Groups API via qontract-api. Client-side S3 state tracks `managed_groups` because the API cannot list all groups.

## Architecture

**Client (`reconcile/ldap_groups_api/`):**

- Loads roles and settings from App-Interface GraphQL
- Builds desired `Group` objects (role LDAP groups and AWS SSO groups)
- Loads `managed_groups` from S3 state
- POSTs desired state + managed names to qontract-api
- Persists `updated_managed_groups` from the task result to S3 on non-dry-run runs, including when the task reports errors (partial apply), then fails the integration so operators are alerted

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
