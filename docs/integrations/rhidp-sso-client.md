# RHIDP SSO Client

**Last Updated:** 2026-07-21

## Description

The `rhidp-sso-client-api` integration manages Keycloak SSO clients for OpenShift/OCM clusters as part of RHIDP (Red Hat Identity Provider). It discovers RHIDP-enabled clusters via OCM subscription/organization labels (through qontract-api's `/external/ocm/clusters` endpoint, not by calling OCM directly), registers or deletes dynamically-registered SSO clients with the appropriate Keycloak realm, and tracks issued SSO client secrets in Vault so they can be consumed by the (not-yet-migrated) `ocm_oidc_idp` integration to configure OIDC identity providers on the clusters.

## Features

- Discover RHIDP-labeled OCM clusters per environment via qontract-api's external OCM endpoint (generic label-based discovery, reusable by other OCM-label-driven integrations)
- Register new SSO clients with the appropriate Keycloak instance's dynamic client registration endpoint
- Delete SSO clients (and their Vault secrets) for clusters no longer desired
- Store SSO client secrets in Vault in a schema byte-compatible with the legacy `ocm_oidc_idp` integration's expectations
- Support multiple Keycloak instances, each with its own initial-access-token secret, potentially stored in a different Vault instance than everything else
- Deterministic create/delete action ordering
- Per-action error isolation — one failing action doesn't abort the whole reconcile run
- Prometheus metrics for managed clusters, SSO client count, IAT expiration, and reconcile success/failure (ported 1:1 from the legacy integration, same metric names)
- Dry-run mode enabled by default

## Desired State Details

Desired state is compiled client-side from two sources:

1. **OCM cluster labels** under the `sre-capabilities.rhidp` namespace, discovered via qontract-api's `/external/ocm/clusters` endpoint and interpreted client-side (label interpretation is deliberately kept out of qontract-api, which stays domain-agnostic):
   - `sre-capabilities.rhidp.name` — auth name (falls back to `--default-auth-name`)
   - `sre-capabilities.rhidp.issuer` — Keycloak issuer URL (falls back to `--default-auth-issuer-url`)
   - `sre-capabilities.rhidp.status` — `enabled` / `disabled` / `enforced` / `sso-client-only` (the deprecated bare `sre-capabilities.rhidp` label takes precedence over `.status` when both are set; missing entirely defaults to `disabled`)
   - `sre-capabilities.rhidp.group-filter-regex` — optional group filter regex passed through to Keycloak
   - Clusters without a console URL, or with external auth enabled, can never get an SSO client and are excluded entirely
   - Clusters are sent to qontract-api regardless of `status` (not just enabled ones) so the `rhidp_managed_clusters` metric reflects every discovered cluster, matching legacy semantics — only `rhidp_enabled=true` clusters are actually reconciled server-side
2. **CLI parameters** — which Keycloak instances exist (issuer URL + Vault secret reference for the instance's initial-access-token), which Vault path to store SSO client secrets under, and default auth name/issuer for clusters without explicit labels

## Architecture

**Client-Side (`reconcile/rhidp_api/sso_client/integration.py`, `reconcile/rhidp_api/common.py`):**

- Iterates OCM environments (GraphQL queries ported into `reconcile/rhidp_api/common.py`, not imported from the legacy `reconcile/rhidp/` package — that whole package is slated for deletion once this migration completes)
- For each environment, calls qontract-api's `/external/ocm/clusters` with `label_key_prefix="sre-capabilities.rhidp"` and the environment's enabled org IDs
- Interprets labels into `SsoClientCluster` desired-state objects (`build_clusters()`)
- Builds `keycloak_instances` (from `--keycloak-instances`) and `vault_target` (from `--vault-input-path`, namespaced per OCM environment)
- POSTs the full desired state to `/integrations/sso-client/reconcile`
- Dry-run: polls for task completion, logs actions, raises `IntegrationError` on errors or timeout
- Non-dry-run: fire-and-forget — the task completes asynchronously and applied actions are published via the events framework

**Server-Side (`qontract_api/integrations/sso_client/`):**

- `service.py` fetches current state (`secret_manager.list(vault_target)`), computes the diff against desired state (only `rhidp_enabled` clusters), and generates `create`/`delete` actions
- `create`: registers the client with the matching Keycloak instance, then writes an `SsoClientSecret` to Vault
- `delete`: reads the stored `SsoClientSecret`, deletes the client from Keycloak (a `401 Unauthorized` is swallowed — the registration token is treated as already invalid, and the Vault secret is still removed), then deletes the Vault secret
- `keycloak_client_factory.py` / `keycloak_workspace_client.py` are the Layer 2 wrapper over `qontract_utils.keycloak_api.KeycloakApi` — no caching (register/delete are mutations, not idempotent reads), just a per-instance-per-client-id distributed lock to prevent concurrent double-registration/deletion
- Cluster discovery itself is handled entirely by the already-existing, domain-agnostic `qontract_api/qontract_api/external/ocm/` endpoint — this integration only calls it, it doesn't own any OCM logic

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/sso-client/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "ocm_environment": "production",
  "clusters": [
    {
      "name": "my-cluster",
      "organization_id": "org-123",
      "console_url": "https://console-openshift-console.apps.my-cluster.example.com",
      "rhidp_enabled": true,
      "auth": {
        "name": "redhat-sso",
        "issuer": "https://auth.redhat.com/auth/realms/EmployeeIDP",
        "group_filter_regex": null
      }
    }
  ],
  "keycloak_secrets": [
    {
      "url": "https://auth.redhat.com/auth/realms/EmployeeIDP",
      "secret": {
        "secret_manager_url": "https://it-vault.corp.redhat.com:8200",
        "path": "apps/sso-iat/share-with/app/ai-app-sre/iat"
      }
    }
  ],
  "vault_target": {
    "secret_manager_url": "https://vault.corp.redhat.com:8200",
    "path": "app-sre/rhidp/sso-client/production"
  },
  "dry_run": true
}
```

**Response:** (202 Accepted)

```json
{
  "id": "uuid-string",
  "status": "pending",
  "status_url": "/api/v1/integrations/sso-client/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/sso-client/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Response:**

```json
{
  "status": "success",
  "actions": [
    {
      "action_type": "create",
      "sso_client_id": "my-cluster-org-123-redhat-sso-auth.redhat.com",
      "cluster_name": "my-cluster",
      "auth_name": "redhat-sso"
    }
  ],
  "applied_actions": [],
  "applied_count": 0,
  "errors": []
}
```

### Models

**Request Fields:**

| Field              | Type                        | Required | Default | Description                                                          |
| ------------------ | --------------------------- | -------- | ------- | ---------------------------------------------------------------------|
| `ocm_environment`  | `string`                    | Yes      | -       | OCM environment name (used as a metric label only)                   |
| `clusters`         | `list[SsoClientCluster]`    | Yes      | -       | All discovered RHIDP-labeled clusters, enabled or not                |
| `keycloak_secrets` | `list[KeycloakInstanceSecret]` | Yes  | -       | One entry per Keycloak instance (issuer URL + Vault IAT reference)   |
| `vault_target`     | `Secret`                    | Yes      | -       | Vault location to store/list/delete SSO client secrets under         |
| `dry_run`          | `bool`                      | No       | `true`  | If true, only calculate actions without executing                    |

**`SsoClientCluster` fields:** `name`, `organization_id`, `console_url` (nullable), `rhidp_enabled`, `auth` (`SsoClientAuth`: `name`, `issuer`, `group_filter_regex`).

**`KeycloakInstanceSecret` fields:** `url` (the Keycloak instance's full issuer URL), `secret` (a `Secret` reference: `secret_manager_url`, `path`, `field`, `version`).

**Validation Rules:**

- `clusters` includes every RHIDP-labeled cluster, not just enabled ones (needed for the `rhidp_managed_clusters` metric) — the server filters by `rhidp_enabled` before diffing
- The SSO client id is computed server-side as `{cluster_name}-{organization_id}-{auth_name}-{issuer_hostname}` and must stay stable across runs — it's the diff key used to detect existing vs. desired clients

**Response Fields:**

| Field             | Type                   | Description                                              |
| ----------------- | ---------------------- | --------------------------------------------------------- |
| `status`          | `TaskStatus`           | Task execution status (pending/success/failed)             |
| `actions`         | `list[SsoClientAction]`| All actions calculated (desired - current)                 |
| `applied_actions` | `list[SsoClientAction]`| Actions successfully applied (non-dry-run only)            |
| `applied_count`   | `int`                  | Number of actions actually applied (0 if `dry_run=true`)   |
| `errors`          | `list[string]`         | Errors encountered during reconciliation                   |

The integration can perform these reconciliation actions:

`create`:

**Description:** Register a new SSO client with the matching Keycloak instance and store its secret in Vault.

**Fields:** `action_type`, `sso_client_id`, `cluster_name`, `auth_name`

**Example:**

```json
{
  "action_type": "create",
  "sso_client_id": "my-cluster-org-123-redhat-sso-auth.redhat.com",
  "cluster_name": "my-cluster",
  "auth_name": "redhat-sso"
}
```

`delete`:

**Description:** Delete an SSO client from Keycloak and remove its stored Vault secret.

**Fields:** `action_type`, `sso_client_id`

**Example:**

```json
{
  "action_type": "delete",
  "sso_client_id": "old-cluster-org-123-redhat-sso-auth.redhat.com"
}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` - must explicitly set to `false` to apply changes
- A cluster missing a console URL at create time is skipped (logged, not counted as an error) rather than failing the run — it's likely just not ready yet
- Deleting a Keycloak client that returns `401 Unauthorized` is treated as "already effectively gone" (the registration token itself may have expired) — the Vault secret is still removed, matching legacy behavior

**Managed Resources:**

- Only clusters with `rhidp_enabled=true` get an SSO client reconciled
- Clusters without a console URL, or with external auth enabled, are excluded entirely — they can never have an SSO client
- Existing SSO clients whose ids are no longer in the desired set **are deleted** — there is no orphan protection here, unlike some other integrations

**Caching:**

- None — the Keycloak Layer 2 client only provides a per-instance, per-client-id distributed lock (via `CacheBackend.lock`) to prevent concurrent double-create/delete, since register/delete are mutations, not cacheable reads

**Other Constraints:**

- The Vault secret schema written for a created SSO client must stay **byte-compatible** with legacy `reconcile/utils/keycloak.py::SSOClient`, since the not-yet-migrated `ocm_oidc_idp` integration reads it directly via `SSOClient(**secret_reader.read_all_secret(secret))`
- Vault delete only supports KV v1 mounts (inherited from `qontract_utils`'s `VaultSecretBackend.delete()`)
- **`KeycloakInstanceSecret.url` must be the full per-realm issuer URL** (e.g. `https://auth.redhat.com/auth/realms/EmployeeIDP`), not just the Keycloak server domain. It's used both as the HTTP client's base URL for the (realm-scoped) dynamic client registration API, and as an exact-string dict key matched against `cluster.auth.issuer` — a bare domain will misroute requests and fail lookups.

## Required Components

**Vault Secrets:**

- One IAT secret per Keycloak instance, referenced via `keycloak_secrets[].secret` — shape `{"current_iat": {"id": ..., "token": ...}, "previous_iat": ...}`. Only `current_iat.token` (a JWT) is used; `previous_iat` (used during token rotation) is not yet consumed. This secret commonly lives in a **different Vault instance** than everything else.
- SSO client secrets storage path (`vault_target`, **KV v1 only**): stores `client_id`, `client_name`, `client_secret`, `redirect_uris`, `registration_access_token`, `registration_client_uri`, `issuer`, `attributes`

**External APIs:**

- OCM API — accessed only via qontract-api's `/external/ocm/clusters` endpoint, never directly
- Keycloak Dynamic Client Registration API (`{issuer}/clients-registrations/default`), per Keycloak realm

**Cache Backend:**

- Redis/Valkey connection required for distributed locking only (no cached data)

## Configuration

**App-Interface Schema:**

[Not applicable — desired state comes from OCM cluster labels, not App-Interface GraphQL schema fields]

**Integration Settings:**

No dedicated settings were added to `qontract_api/qontract_api/config.py` for this integration; it uses the shared task-timeout settings common to all integrations.

## Client Integration

**File:** `reconcile/rhidp_api/sso_client/integration.py` (shared helpers in `reconcile/rhidp_api/common.py`)

**CLI Command:** `qontract-reconcile integration rhidp-sso-client-api`

**Arguments and Options:**

- `--keycloak-instances` (required): a JSON array, one entry per Keycloak instance, e.g. `[{"url": "https://auth.redhat.com/auth/realms/EmployeeIDP", "secret": {"secret_manager_url": "https://it-vault.corp.redhat.com:8200", "path": "apps/sso-iat/share-with/app/ai-app-sre/iat"}}]`
- `--vault-input-path` (required): base Vault path to store/list/delete SSO client secrets under (namespaced per OCM environment automatically)
- `--ocm-env` (optional, envvar `RHIDP_OCM_ENV`): restrict to a single OCM environment; omit to process all
- `--default-auth-name` (default `redhat-sso`, envvar `RHIDP_DEFAULT_AUTH_NAME`)
- `--default-auth-issuer-url` (default `https://auth.redhat.com/auth/realms/EmployeeIDP`, envvar `RHIDP_DEFAULT_AUTH_ISSUER_URL`)

**Client Architecture:**

- Loops over all (or one filtered) OCM environment, independently discovering clusters and POSTing a separate reconcile request per environment
- The legacy `reconcile/rhidp/sso_client` integration keeps running side by side — no feature-flag cutover has happened yet, and `reconcile/rhidp/` is not touched by this migration

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/sso_client/](../../qontract_api/qontract_api/integrations/sso_client/)
- Client: [reconcile/rhidp_api/sso_client/integration.py](../../reconcile/rhidp_api/sso_client/integration.py)
- Shared Layer 1 clients: [qontract_utils/qontract_utils/keycloak_api/](../../qontract_utils/qontract_utils/keycloak_api/), [qontract_utils/qontract_utils/ocm_api/](../../qontract_utils/qontract_utils/ocm_api/)
- External endpoint used: [qontract_api/qontract_api/external/ocm/](../../qontract_api/qontract_api/external/ocm/)

**External:**

- [Keycloak Dynamic Client Registration](https://www.keycloak.org/docs/latest/securing_apps/#_client_registration)
- [OpenShift Cluster Manager (OCM) API](https://api.openshift.com/)
