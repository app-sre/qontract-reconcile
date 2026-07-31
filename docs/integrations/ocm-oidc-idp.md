# OCM OIDC Identity Provider

**Last Updated:** 2026-07-31

## Description

The `ocm-oidc-idp-api` integration manages OCM Identity Provider (IDP) configuration for OpenShift/OCM clusters as part of RHIDP (Red Hat Identity Provider). It discovers RHIDP-enabled clusters via OCM subscription/organization labels (through qontract-api's `/external/ocm/clusters` endpoint, not by calling OCM directly), and reconciles each cluster's OCM `OpenIDIdentityProvider` config to point at the Keycloak SSO client that the sibling `sso-client-api` integration registers and stores in Vault. It does not create Keycloak clients itself — the two integrations are coupled only through the Vault secret `sso-client-api` writes and this integration reads.

## Features

- Discover RHIDP-labeled OCM clusters per environment via qontract-api's external OCM endpoint (reuses the same generic, label-based discovery as `sso-client-api`)
- Fetch existing OCM identity providers per cluster (cached, with cache invalidation on any create/update/delete)
- Create, update, or delete the cluster's `OpenIDIdentityProvider` to match the desired SSO client configuration
- Read desired OIDC configuration (client id/secret/issuer, optional group-filter claim) from the Vault secret `sso-client-api` wrote for that cluster
- Skip removal of foreign/unmanaged identity providers (e.g. a manually-configured GitHub IDP) unless the cluster's status is `enforced`, in which case all foreign IDPs are removed
- Per-cluster error isolation on both the OCM fetch and the Vault secret read/parse — one unreachable cluster or one malformed secret does not abort the rest of the environment's reconcile (this fixes a real fragility in the legacy integration, which let a single bad secret crash the whole run)
- Prometheus metrics for managed clusters (shared with `sso-client-api`) and reconcile success/failure (ported 1:1 from the legacy integration, same metric names)
- Dry-run mode enabled by default

## Desired State Details

Desired state is compiled from two sources:

1. **OCM cluster labels** under the `sre-capabilities.rhidp` namespace, discovered via qontract-api's `/external/ocm/clusters` endpoint and interpreted client-side (label interpretation is deliberately kept out of qontract-api, which stays domain-agnostic):
   - `sre-capabilities.rhidp.name` — auth/IDP name (falls back to `--default-auth-name`)
   - `sre-capabilities.rhidp.issuer` — Keycloak issuer URL (falls back to `--default-auth-issuer-url`)
   - `sre-capabilities.rhidp.status` — `enabled` / `disabled` / `enforced` / `sso-client-only` (the deprecated bare `sre-capabilities.rhidp` label takes precedence over `.status` when both are set; missing entirely defaults to `disabled`). The client translates this into two plain booleans sent to the server — `oidc_enabled` (`status` not in `{disabled, sso-client-only}`) and `enforced` (`status == enforced`) — so the server has zero knowledge of label/status semantics.
   - `sre-capabilities.rhidp.group-filter-regex` — optional; if set, the desired IDP's claims map a `groups` claim to the `filtered_groups` Keycloak client scope
   - Clusters without a console URL, or with external auth enabled, can never have an OIDC identity provider configured and are excluded entirely
   - Clusters are sent to qontract-api regardless of `oidc_enabled` (not just enabled ones) so a cluster that becomes disabled still has its stale identity provider cleaned up
2. **Vault secret** written by `sso-client-api` (read server-side, not client-side): `client_id`, `client_secret`, `issuer`, `attributes["group-filter-regex"]`. If the stored `issuer` doesn't match the cluster's configured issuer, or the secret is missing/malformed, that cluster's OIDC config is skipped for this reconcile (logged, not a fatal error)
3. **CLI parameters** — which Vault path to read SSO client secrets from (must match the same path `sso-client-api` writes to), and default auth name/issuer for clusters without explicit labels

## Architecture

**Client-Side (`reconcile/rhidp_api/ocm_oidc_idp/integration.py`, `reconcile/rhidp_api/common.py`):**

- Iterates OCM environments (GraphQL queries ported into `reconcile/rhidp_api/common.py`, not imported from the legacy `reconcile/rhidp/` package — that whole package is slated for deletion once this migration completes)
- For each environment, calls qontract-api's `/external/ocm/clusters` with `label_key_prefix="sre-capabilities.rhidp"` and the environment's enabled org IDs
- Interprets labels into `OcmOidcIdpCluster` desired-state objects (`build_clusters()`)
- Builds `ocm_connection` (OCM environment connection details, needed server-side for IDP CRUD) and `vault_target` (from `--vault-input-path`, namespaced per OCM environment — must match `sso-client-api`'s own path exactly)
- POSTs the full desired state to `/integrations/ocm-oidc-idp/reconcile`
- Dry-run: polls for task completion, logs actions, raises `IntegrationError` on errors or timeout
- Non-dry-run: fire-and-forget — the task completes asynchronously and applied actions are published via the events framework

**Server-Side (`qontract_api/integrations/ocm_oidc_idp/`):**

- `service.py` fetches current state (`OcmWorkspaceClient.get_identity_providers()` per cluster) and desired state (Vault secret read + parse per `oidc_enabled` cluster), diffs via `qontract_utils.differ.diff_iterables`, and generates `create`/`update`/`delete` actions
- `create`/`update`: calls the corresponding `OcmWorkspaceClient` method, which invalidates that cluster's identity-provider cache entry on success
- `delete`: skipped for a foreign-named IDP unless the cluster is `enforced`, in which case it's removed regardless of name
- Cluster discovery itself is handled entirely by the already-existing, domain-agnostic `qontract_api/qontract_api/external/ocm/` endpoint — this integration only calls it, it doesn't own any OCM cluster-discovery logic
- OCM Identity Provider CRUD is new Layer 1 (`qontract_utils/qontract_utils/ocm_api/`) and Layer 2 (`qontract_api/qontract_api/external/ocm/ocm_workspace_client.py`) code added specifically for this migration — parameterized by `cluster_id`/`idp_id` (not the `Filter` DSL used for clusters/subscriptions/labels), since identity providers are a per-cluster nested resource, not a searchable collection

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/ocm-oidc-idp/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "ocm_environment": "production",
  "ocm_connection": {
    "secret_manager_url": "https://vault.corp.redhat.com:8200",
    "path": "app-sre/creds/ocm/production",
    "ocm_url": "https://api.openshift.com",
    "access_token_url": "https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token",
    "access_token_client_id": "client-id"
  },
  "clusters": [
    {
      "cluster_id": "abc123",
      "name": "my-cluster",
      "organization_id": "org-123",
      "auth": {
        "name": "redhat-sso",
        "issuer": "https://auth.redhat.com/auth/realms/EmployeeIDP",
        "group_filter_regex": null,
        "oidc_enabled": true,
        "enforced": false
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
  "status_url": "/api/v1/integrations/ocm-oidc-idp/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/ocm-oidc-idp/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: immediate status)

**Response:**

```json
{
  "status": "success",
  "actions": [
    {
      "action_type": "create",
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

| Field             | Type                    | Required | Default | Description                                                                    |
| ----------------- | ----------------------- | -------- | ------- | -------------------------------------------------------------------------------|
| `ocm_environment` | `string`                | Yes      | -       | OCM environment name (used as a metric label only)                             |
| `ocm_connection`  | `OcmConnectionParams`   | Yes      | -       | OCM base URL, OAuth2 token endpoint/client id, and Vault reference to the client secret — needed for identity provider CRUD |
| `clusters`        | `list[OcmOidcIdpCluster]` | Yes    | -       | All discovered RHIDP-labeled clusters, `oidc_enabled` or not                    |
| `vault_target`    | `Secret`                | Yes      | -       | Vault location `sso-client-api` stores SSO client secrets under (field/version unused) |
| `dry_run`         | `bool`                  | No       | `true`  | If true, only calculate actions without executing                              |

**`OcmOidcIdpCluster` fields:** `cluster_id`, `name`, `organization_id`, `auth` (`OcmOidcIdpAuth`: `name`, `issuer`, `group_filter_regex`, `oidc_enabled`, `enforced`).

**Validation Rules:**

- `clusters` includes every RHIDP-labeled cluster, not just `oidc_enabled` ones — a disabled cluster's stale identity provider is still detected and removed
- The Vault secret path for a cluster is computed server-side as `{vault_target.path}/{cluster_name}-{organization_id}-{auth_name}-{issuer_hostname}` — this must match exactly the id `sso-client-api` uses when writing the secret

**Response Fields:**

| Field             | Type                     | Description                                              |
| ----------------- | ------------------------ | --------------------------------------------------------- |
| `status`          | `TaskStatus`             | Task execution status (pending/success/failed)             |
| `actions`         | `list[OcmOidcIdpAction]` | All actions calculated (desired - current)                 |
| `applied_actions` | `list[OcmOidcIdpAction]` | Actions successfully applied (non-dry-run only)            |
| `applied_count`   | `int`                    | Number of actions actually applied (0 if `dry_run=true`)   |
| `errors`          | `list[string]`           | Errors encountered during reconciliation                   |

The integration can perform these reconciliation actions:

`create`:

**Description:** Create a new OIDC identity provider on the cluster.

**Fields:** `action_type`, `cluster_name`, `auth_name`

**Example:**

```json
{
  "action_type": "create",
  "cluster_name": "my-cluster",
  "auth_name": "redhat-sso"
}
```

`update`:

**Description:** Update an existing OIDC identity provider's configuration (e.g. issuer, client id/secret, or claims changed).

**Fields:** `action_type`, `cluster_name`, `auth_name`

**Example:**

```json
{
  "action_type": "update",
  "cluster_name": "my-cluster",
  "auth_name": "redhat-sso"
}
```

`delete`:

**Description:** Delete an identity provider from the cluster (either a managed OIDC IDP no longer desired, or — only when the cluster is `enforced` — a foreign identity provider of any type).

**Fields:** `action_type`, `cluster_name`, `idp_name`

**Example:**

```json
{
  "action_type": "delete",
  "cluster_name": "my-cluster",
  "idp_name": "redhat-sso"
}
```

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` - must explicitly set to `false` to apply changes
- A malformed or unreadable Vault secret for a cluster is skipped (logged, not counted as an error) rather than failing the whole environment's reconcile
- An OCM fetch failure for one cluster is skipped (logged) without affecting other clusters in the same reconcile
- Only `OpenIDIdentityProvider` type identity providers are ever created or updated — a desired identity provider of any other type is logged as an error and skipped, never sent to OCM

**Managed Resources:**

- Only clusters with `oidc_enabled=true` get a desired OIDC identity provider computed; disabled clusters still have their current state checked so a stale managed IDP gets removed
- Clusters without a console URL, or with external auth enabled, are excluded entirely — they can never have an identity provider configured
- An identity provider whose name doesn't match the cluster's configured auth name is left alone (treated as unmanaged/foreign) **unless** the cluster's status is `enforced`, in which case it is deleted regardless of type or name

**Caching:**

- Identity provider lists are cached per `(OCM environment, cluster_id)` via `OcmWorkspaceClient` (TTL: `settings.ocm.identity_providers_cache_ttl`, default 5 minutes), using the same double-checked-locking pattern as cluster discovery
- Any successful create/update/delete invalidates that cluster's cache entry immediately, so the next read reflects the change instead of serving stale state

**Other Constraints:**

- The Vault secret schema this integration reads must stay **byte-compatible** with what `sso-client-api` writes (`qontract_api/rhidp/domain.py::SsoClientSecret`) — both integrations share this module
- OCM's identity provider wire format accepts the same field names as the internal Python models (no camelCase aliasing needed) — confirmed empirically against the legacy `reconcile/utils/ocm/identity_providers.py` implementation

## Required Components

**Vault Secrets:**

- SSO client secrets (`vault_target`, read-only here, written by `sso-client-api`): `client_id`, `client_name`, `client_secret`, `redirect_uris`, `registration_access_token`, `registration_client_uri`, `issuer`, `attributes`
- OCM access token client secret (`ocm_connection`, resolved server-side via `SecretManager`)

**External APIs:**

- OCM API — accessed only via qontract-api (`/external/ocm/clusters` for discovery, and the internal `OcmWorkspaceClient`/`OcmApi` Layer 2/1 for identity provider CRUD), never directly from the client

**Cache Backend:**

- Redis/Valkey connection required for both cluster discovery caching (shared with `sso-client-api`) and identity provider list caching (`ocm:idps:<environment_key>:<cluster_id>`)

## Configuration

**App-Interface Schema:**

[Not applicable — desired state comes from OCM cluster labels, not App-Interface GraphQL schema fields]

**Integration Settings:**

| Setting                          | Environment Variable                     | Default | Description                                   |
| --------------------------------- | ----------------------------------------- | ------- | ---------------------------------------------- |
| `identity_providers_cache_ttl`    | `QAPI_OCM__IDENTITY_PROVIDERS_CACHE_TTL`  | `300`   | Identity provider list cache TTL, in seconds   |

## Client Integration

**File:** `reconcile/rhidp_api/ocm_oidc_idp/integration.py` (shared helpers in `reconcile/rhidp_api/common.py`)

**CLI Command:** `qontract-reconcile integration ocm-oidc-idp-api`

**Arguments and Options:**

- `--vault-input-path` (required): base Vault path to read SSO client secrets from (namespaced per OCM environment automatically) — must match `sso-client-api`'s own `--vault-input-path`
- `--ocm-env` (optional, envvar `RHIDP_OCM_ENV`): restrict to a single OCM environment; omit to process all
- `--default-auth-name` (default `redhat-sso`, envvar `RHIDP_DEFAULT_AUTH_NAME`)
- `--default-auth-issuer-url` (default `https://auth.redhat.com/auth/realms/EmployeeIDP`, envvar `RHIDP_DEFAULT_AUTH_ISSUER_URL`)

**Client Architecture:**

- Loops over all (or one filtered) OCM environment, independently discovering clusters and POSTing a separate reconcile request per environment
- The legacy `reconcile/rhidp/ocm_oidc_idp` integration keeps running side by side — no feature-flag cutover has happened yet, and `reconcile/rhidp/` is not touched by this migration

## Troubleshooting

**Common Issues:**

**Issue: A cluster's identity provider is never created**

- **Symptom:** No `create` action appears for a cluster you expect to have RHIDP OIDC enabled
- **Cause:** `sso-client-api` hasn't registered a Keycloak client for that cluster yet (no Vault secret at the expected path), or the cluster's `sre-capabilities.rhidp.status` label resolves to `disabled`/`sso-client-only`
- **Solution:** Confirm `sso-client-api` has successfully reconciled that cluster first (this integration only configures OCM, never Keycloak), and check the cluster's OCM labels

**Issue: Foreign identity providers keep reappearing in the diff but are never deleted**

- **Symptom:** A non-managed identity provider (e.g. a manually added GitHub IDP) shows up every run but is never removed
- **Cause:** This is expected — foreign IDPs are left alone unless the cluster's status is `enforced`
- **Solution:** Set `sre-capabilities.rhidp.status: enforced` on the cluster if the intent is for RHIDP to fully own its identity providers

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/ocm_oidc_idp/](../../qontract_api/qontract_api/integrations/ocm_oidc_idp/)
- Client: [reconcile/rhidp_api/ocm_oidc_idp/integration.py](../../reconcile/rhidp_api/ocm_oidc_idp/integration.py)
- Shared Vault domain: [qontract_api/qontract_api/rhidp/domain.py](../../qontract_api/qontract_api/rhidp/domain.py)
- Shared Layer 1/2 OCM clients: [qontract_utils/qontract_utils/ocm_api/](../../qontract_utils/qontract_utils/ocm_api/), [qontract_api/qontract_api/external/ocm/](../../qontract_api/qontract_api/external/ocm/)

**External:**

- [OpenShift Cluster Manager (OCM) API](https://api.openshift.com/)
- [OCM Identity Providers API reference](https://api.openshift.com/api/clusters_mgmt/v1/) (`/clusters/{id}/identity_providers`)
