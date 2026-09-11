# Managed SSO Client Integration

**Last Updated:** 2026-09-10

## Description

The `managed-sso-client` integration lets tenants declaratively request SSO clients on Keycloak directly from App-Interface, instead of filing a manual SNOW ticket or piggybacking on the OCM-cluster-driven `rhidp-sso-client` flow. It reconciles a tenant's declared client against Keycloak's client-registration API, supporting full create/update/delete lifecycle management. **Milestone 1 scope: OpenID Connect (OIDC) only** — SAML support and tenant-namespace secret delivery via an openshiftResources provider are deferred to a future milestone (see [APPSRE-15234](https://redhat.atlassian.net/browse/APPSRE-15234)).

## Features

- Creates OIDC clients declared in App-Interface via Keycloak's `/clients-registrations/default` endpoint
- Updates clients in place via live `GET`/diff/`PUT` against Keycloak — no forced secret rotation on unrelated config changes
- Deletes clients removed from App-Interface (treats 401/404 from Keycloak as already-deleted)
- Exposes the most commonly needed OIDC `ClientRepresentation` fields (client type, grants, redirect/logout/CORS URIs, consent, scopes) - anything else keeps its realm/Keycloak default
- Splits credential storage: an AppSRE-owned Vault secret (full Keycloak response, including the `registration_access_token`) and a tenant-facing Vault secret (`client_id`/`client_secret` only)
- Supports bringing your own Keycloak instance/realm and initial access token (IAT) via a separate `keycloak-instance-1.yml` reference
- Per-client error isolation: one client's failure does not abort reconciliation for the rest
- Client naming is derived, not tenant-chosen: `clientId = "<app.name>-<name>"`, guaranteeing uniqueness across the realm
- Dry-run mode calculates actions (including live-Keycloak diffing) without applying anything
- Exposes `managed_sso_clients_managed`, a Prometheus gauge tracking how many managed SSO clients are currently tracked in Vault

## Desired State Details

Desired state is compiled from `managed_sso_clients_v1` in App-Interface (schema `/dependencies/managed-sso-client-1.yml`). Each object references:

- `app` — crossref to `/app-sre/app-1.yml`, whose `name` is used to derive the Keycloak `clientId`
- `enabled` — optional, defaults to `true`; set to `false` to deactivate the client on Keycloak in place without deleting this object (which would delete the Keycloak registration and its secret entirely)
- `keycloakInstance` — crossref to `/dependencies/keycloak-instance-1.yml` (`url` - the full realm base URL, e.g. `https://host/auth/realms/name` - plus an `initialAccessToken` Vault ref); AppSRE publishes instances for `auth.redhat.com`/`auth.stage.redhat.com`, or a tenant can reference their own instance file for "bring your own IAT"
- `protocol` — only `openid-connect` is accepted in this milestone (schema-level `saml` support is reserved for later)
- `oidc` — inline OIDC configuration (`/dependencies/managed-sso-client-oidc-1.yml`); `redirectUris` is the only required field
- `output` — optional Vault path for the tenant-facing credential secret; if omitted, the reconciler picks an integration-managed default path

**Example client definition:**

```yaml
$schema: /dependencies/managed-sso-client-1.yml
name: ci-bot
description: CI client for my-app
app:
  $ref: /services/my-app/app.yml
keycloakInstance:
  $ref: /dependencies/keycloak-instances/auth-redhat-com.yml
oidc:
  redirectUris:
  - https://my-app.example.com/callback
  serviceAccountsEnabled: true
```

Renaming a client (changing `name`) changes its derived `clientId`, which the reconciler treats as a delete of the old client plus a create of a new one — not an in-place rename — issuing new credentials.

## Architecture

**Client-Side (`reconcile/managed_sso_client/integration.py`):**

- `managed_sso_clients_v1` is a protocol-discriminated GraphQL interface (`managed-sso-client-1.yml`'s `oneOf` on `protocol` maps to `interfaceResolve` in `graphql-schemas/schema.yml`), so the generated query result already resolves each client to a concrete type — `ManagedSsoClientOpenidConnectV1` is the only one today. `compile_desired_state()` uses a `match`/`case` on that concrete type, not a manual `protocol` string comparison; a client that doesn't resolve to any known type (schema/client version skew) falls through to a `case _` that raises `IntegrationError`
- Does **not** resolve `accessType`'s schema-declared `default: confidential` client-side (JSON Schema `default:` values aren't injected into the GraphQL response). Passes `null` straight through - the server always resolves an unset `accessType` to confidential via a Pydantic validator. Keycloak's own client-registration default for an omitted `publicClient`/`bearerOnly` pair is **public**, not confidential (verified against a live instance), so the server can't rely on omission the way it does for every other optional field
- Sends the complete desired state to qontract-api in a single request
- In dry-run: polls for task completion, logs planned actions, raises `IntegrationError` on errors or timeout
- In non-dry-run: fire-and-forget (task completes asynchronously; the next scheduled run re-queues, deduplication prevents overlap)

**Server-Side (`qontract_api/integrations/managed_sso_client/`):**

- Vault remains the source of truth for which clients currently exist (Keycloak's registration API has no "list clients" endpoint) — `secret_manager.list()` against the AppSRE-owned management prefix
- For clients tracked in both Vault and desired state: fetches the live representation via `GET` (does not rotate the registration token), projects both sides through `comparable_client_state()` (excluding server-owned fields `id`/`secret`/`registration_access_token`), and diffs
- Applies `PUT` only when drift is detected; `PUT` rotates the registration access token, which is durably persisted back to Vault before the update is considered complete
- Independent of the existing OCM-cluster-driven `sso_client` integration (per ADR-007, no cross-integration imports) — reuses only the extended Layer-1 Keycloak API client

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/managed-sso-client/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "desired_clients": [
    {
      "client_id": "my-app-ci-bot",
      "keycloak_instance": {
        "url": "https://auth.redhat.com/auth/realms/redhat-external",
        "initial_access_token": {
          "secret_manager_url": "https://vault.example.com",
          "path": "app-sre/keycloak/iat",
          "field": "token"
        }
      },
      "oidc": {
        "redirect_uris": ["https://my-app.example.com/callback"]
      }
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
  "status_url": "/api/v1/integrations/managed-sso-client/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/managed-sso-client/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

- `timeout` (optional): Block up to N seconds for completion (default: API default timeout)

**Response:**

```json
{
  "status": "success",
  "actions": [],
  "applied_actions": [],
  "applied_count": 0,
  "errors": []
}
```

### Models

**Request Fields:**

| Field             | Type                                 | Required | Default | Description                                                  |
| ----------------- | ------------------------------------ | -------- | ------- | ------------------------------------------------------------ |
| `desired_clients` | `list[ManagedSsoClientDesiredState]` | Yes      | -       | All tenant-declared managed SSO clients across App-Interface |
| `dry_run`         | `bool`                               | No       | `true`  | If true, only calculate actions without executing            |

**Validation Rules:**

- `redirectUris` is the only required OIDC field; every other OIDC field is optional
- `client_id` is taken as-is by the server; deriving it from `<app.name>-<name>` is the client-side integration's job, not a server-side validation rule

**Response Fields:**

| Field             | Type                           | Description                                                |
| ----------------- | ------------------------------ | ---------------------------------------------------------- |
| `status`          | `TaskStatus`                   | Task execution status (pending/success/failed/skipped)     |
| `actions`         | `list[ManagedSsoClientAction]` | All actions calculated, including any that failed to apply |
| `applied_actions` | `list[ManagedSsoClientAction]` | Actions successfully applied (non-dry-run only)            |
| `applied_count`   | `int`                          | Number of actions actually applied (0 if dry_run=True)     |
| `errors`          | `list[string]`                 | Errors encountered during validation, diffing, or apply    |

The integration can perform these reconciliation actions:

`create`:

**Description:** Register a new client with Keycloak and persist both the AppSRE-owned and tenant-facing secrets.

**Fields:**

- `client_id`
- `tenant_secret_path` — Vault path of the tenant-facing credential secret this action wrote to

`update`:

**Description:** OIDC configuration drift only — updates the client in place via live `GET`/diff/`PUT`. Rotates and persists the registration access token; leaves `client_secret` unchanged. Never touches the tenant secret's Vault path; that's an independent concern, see `move_tenant_secret` below.

**Fields:**

- `client_id`

`move_tenant_secret`:

**Description:** A changed `output` path — migrates the tenant secret to the new Vault path (reusing the existing `client_secret`, no Keycloak call) and deletes the old copy. Independent of, and detected/emitted separately from, `update` — changing `output` alone with no OIDC drift produces only this action, not an `update`. When both drift at once, both actions are emitted for the same `client_id`, with `move_tenant_secret` always applied before `update` so the migrated path isn't reverted by the update's own persisted state.

**Fields:**

- `client_id`
- `tenant_secret_path` — new Vault path of the tenant-facing credential secret

**Known limitation:** if deleting the old tenant secret copy fails after the new one is successfully written, this is logged as a warning (not a task error) and the old copy is orphaned — it will not be cleaned up automatically on a later reconcile, since the management secret's `tenant_secret_path` has already moved on. Manual cleanup is required in that case.

`delete`:

**Description:** Delete a client no longer present in desired state, and remove both its Vault secrets.

**Fields:**

- `client_id`

## Limits and Constraints

**Safety:**

- `dry_run` defaults to `true` — must explicitly set to `false` to apply changes
- Clients present in Keycloak/Vault but absent from App-Interface are deleted; there is no "orphan protection" opt-out for this integration (unlike some other integrations) since Vault is the sole source of truth for current state
- A failed Vault write during create rolls back the Keycloak registration
- Before creating a client, the reconciler verifies qontract-api's Vault service account can actually write to both the AppSRE-owned management secret path and the tenant secret path (default or custom `output`) — via Vault's `sys/capabilities-self` API, checked unconditionally rather than assuming either is writable. Visible as an error in **dry-run**, before the Keycloak client is ever registered. This is a static policy check, not a full guarantee: Vault's KV v2 create-vs-update ACL distinction depends on whether a version already exists at the path at write time, which the check can't see — a policy granting only `update` could still be denied on an actual first write
- **Known risk:** if `PUT` succeeds on Keycloak but persisting the rotated token to Vault fails, that client's stored token is permanently stale until manually recovered — this does **not** self-heal on the next reconcile. Surfaced as a distinct `ManagedSsoClientTokenPersistError` and a dedicated `managed_sso_client_token_persist_failures` counter; treat any non-zero rate as needing immediate investigation

**Managed Resources:**

- Only `openid-connect` clients are supported in this milestone; a `saml` protocol value is rejected client-side

**Rate Limiting:**

- No integration-specific rate limiting; subject to Keycloak's own request limits

**Caching:**

- A client's live Keycloak representation (fetched by `get_client`, used for drift detection) is cached per client_id with a TTL (default 1 hour, `QAPI_MANAGED_SSO_CLIENT__CLIENT_CACHE_TTL`), since Keycloak has no change-notification mechanism to invalidate it proactively otherwise
- `update_client`/`delete_client` invalidate that cache entry immediately, so a change is always visible on the very next read
- The same key (`managed-sso-client:{keycloak_instance_url}:{client_id}`) doubles as the per-instance distributed lock, preventing concurrent reconcile runs from racing on the same client

**Other Constraints:**

- The AppSRE-owned Vault mount for this integration's secrets must be KV v1 — `SecretManager.delete()` has no KV v2 implementation yet (same constraint the existing `sso_client` integration already operates under)
- Verified against a live Keycloak instance: `PUT /clients-registrations/default/{clientId}` merges by field — an omitted field is left unchanged, not reset to Keycloak's default. `postLogoutRedirectUris` is the only OIDC field carried inside Keycloak's `attributes` map (as a `##`-joined string) rather than as a top-level property
- `keycloak-instance-1.yml`'s `url` must be the complete realm base URL (e.g. `https://host/auth/realms/name`), not the bare Keycloak server URL - nothing derives or appends a realm path to it
- **Unset vs. explicitly empty for optional OIDC list/boolean fields** (`webOrigins`, `defaultClientScopes`, `optionalClientScopes`, `postLogoutRedirectUris`, `serviceAccountsEnabled`, `consentRequired`, `fullScopeAllowed`): leaving one of these unset in App-Interface means "don't manage this field" — it's never sent to Keycloak (merges by field, so the existing value is left untouched) and never compared for drift. Explicitly setting a field to `[]`/`false` is a real desired value — it's sent on create/update and does get diffed. This matters because the two are *not* interchangeable: coercing "unset" into an empty list would force it cleared on every create/update instead of leaving it alone
- **Caution: removing a previously-set field does not revert it.** For every field in the bullet above, going from an explicit value back to unset only stops managing that field — it does not reset Keycloak to any default. The live value stays frozen at whatever was last pushed. To actually undo a change, push back the field's previous explicit value (or Keycloak's own default) instead of deleting the key
- `accessType` and `directAccessGrantsEnabled` are the two exceptions to the above: both always resolve to an explicit value (confidential access type; direct access grants disabled) even when left unset, because Keycloak's own create-time defaults for these two are insecure (public access type; direct access grants enabled) — verified against a live instance. Unlike the fields above, these are always sent and always diffed, so removing the key from App-Interface does *not* freeze them; reconcile re-applies the secure default on the very next run

## Required Components

**Vault Secrets:**

- Per-instance `initialAccessToken` (from `keycloak-instance-1.yml`): IAT used to register new clients on that realm. Accepts either of Vault's two coexisting IAT shapes (see `qontract_api.keycloak_iat.resolve_initial_access_token`, shared with `rhidp-sso-client-api`): IT's rotation format `{"current_iat": {"id": ..., "token": ...}, "previous_iat": ...}`, or a plain secret with the token as the value of `initialAccessToken.field`
- `app-sre/integrations-throughput/managed-sso-client/management/<client_id>` (default prefix, configurable): AppSRE-owned, full Keycloak registration response — never tenant-facing
- `<output path>` or `app-sre/integrations-throughput/managed-sso-client/output/<client_id>` (default): tenant-facing `client_id`/`client_secret`

**External APIs:**

- Keycloak Client Registration API
  - Base URL: the full realm URL from App-Interface's `keycloakInstance.url` (e.g. `https://auth.redhat.com/auth/realms/redhat-external`)
  - Authentication: Bearer token (realm IAT for create; per-client `registration_access_token` for get/update/delete)
  - HTTPS enforced for all managed-sso-client Keycloak instances (tenant-supplied URLs are not trusted to already be HTTPS)

**Cache Backend:**

- Redis/Valkey connection required, for both distributed locking and the per-client representation cache

## Configuration

**App-Interface Schema:**

```yaml
$schema: /dependencies/managed-sso-client-1.yml
name: ci-bot
app:
  $ref: /services/my-app/app.yml
keycloakInstance:
  $ref: /dependencies/keycloak-instances/auth-redhat-com.yml
oidc:
  redirectUris:
  - https://my-app.example.com/callback
```

**Integration Settings:**

| Setting                          | Environment Variable                                        | Default                                                         | Description                                                                        |
| -------------------------------- | ----------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Management Vault path prefix     | `QAPI_MANAGED_SSO_CLIENT__VAULT_PATH_PREFIX`                | `app-sre/integrations-throughput/managed-sso-client/management` | AppSRE-owned secret prefix                                                         |
| Default output Vault path prefix | `QAPI_MANAGED_SSO_CLIENT__DEFAULT_OUTPUT_VAULT_PATH_PREFIX` | `app-sre/integrations-throughput/managed-sso-client/output`     | Used when a client sets no explicit `output`                                       |
| Client cache TTL                 | `QAPI_MANAGED_SSO_CLIENT__CLIENT_CACHE_TTL`                 | `3600` (1 hour)                                                 | Seconds a fetched client representation stays cached before Keycloak is re-queried |

## Client Integration

**File:** `reconcile/managed_sso_client/integration.py`

**CLI Command:** `qontract-reconcile managed-sso-client`

**Client Architecture:**

1. Queries `managed_sso_clients_v1` — a protocol-discriminated GraphQL interface — including the `... on ManagedSsoClientOpenidConnect_v1 { oidc { ... } }` inline fragment and the `keycloakInstance`/`app` crossrefs
2. Pattern-matches each query result on its concrete generated type (`case ManagedSsoClientOpenidConnectV1(): ...`); a client that doesn't resolve to a known type raises `IntegrationError` via the fallback `case _`
3. Passes an unset `accessType` through as `None` rather than resolving it to a default - it's unmanaged unless the tenant sets it
4. Sends one `POST /api/v1/integrations/managed-sso-client/reconcile` request for all clients
5. In **dry-run**: polls `GET /reconcile/{task_id}`, logs actions, raises `IntegrationError` on errors or timeout
6. In **non-dry-run**: returns immediately after queuing (fire-and-forget)

**Example (dry-run via CLI):**

```bash
qontract-reconcile managed-sso-client --dry-run
```

## Troubleshooting

**Issue: Task times out in dry-run**

- **Symptom:** `IntegrationError: task did not complete within the timeout period`
- **Cause:** The Celery worker is overloaded, not running, or a live Keycloak `GET` during diffing is slow/unreachable
- **Solution:** Check Celery worker health and Keycloak instance reachability

**Issue: `managed_sso_client_token_persist_failures` counter is non-zero**

- **Symptom:** A client update rotated its Keycloak registration token but the new token failed to persist to Vault
- **Cause:** Vault outage or connectivity issue coinciding with an update
- **Solution:** This does not self-heal — investigate immediately. Once Vault recovers, re-run reconcile; if the token is unrecoverable, the client must be deleted and recreated (new credentials)

**Issue: 401/403 from Keycloak on update or delete**

- **Symptom:** Diff/apply fails for a client; recorded in `errors`
- **Cause:** The realm's IAT or the client's stored `registration_access_token` is invalid/expired
- **Solution:** Verify the `keycloak-instance-1.yml`'s `initialAccessToken` is current; for a stale per-client token, the client may need to be deleted and recreated

## References

**Code:**

- Server: [qontract_api/qontract_api/integrations/managed_sso_client/](../../qontract_api/qontract_api/integrations/managed_sso_client/)
- Client: [reconcile/managed_sso_client/integration.py](../../reconcile/managed_sso_client/integration.py)
- Layer 1 Keycloak client: [qontract_utils/qontract_utils/keycloak_api/](../../qontract_utils/qontract_utils/keycloak_api/)
- GQL definitions: [reconcile/gql_definitions/managed_sso_client/](../../reconcile/gql_definitions/managed_sso_client/)

**Design doc:**

- [Expose managed SSO client capability to tenants via a dedicated app-interface schema](https://github.com/openshift-online/platform-engineering-enhancements/pull/83) (APPSRE-15234)

**External:**

- [Keycloak Client Registration API](https://www.keycloak.org/docs/latest/securing_apps/#_client_registration)
