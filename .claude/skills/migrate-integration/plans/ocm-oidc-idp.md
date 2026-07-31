# Migration Plan: `reconcile/rhidp/ocm_oidc_idp` → qontract-api

JIRA: [APPSRE-13595](https://redhat.atlassian.net/browse/APPSRE-13595) — Part 2 of the RHIDP capability migration.
Part 1 (`rhidp/sso_client` → `rhidp-sso-client-api`) shipped in [PR #5689](https://github.com/app-sre/qontract-reconcile/pull/5689) (JIRA APPSRE-13596) and is the primary reference implementation for this migration.

## Status: Migration complete (all phases 1-6 shipped)

Final naming correction applied post-implementation: the new integration's own name
is `ocm-oidc-idp-api` (not `rhidp-ocm-oidc-idp-api`) and `metrics.INTEGRATION_NAME` is
`ocm-oidc-idp` (not `rhidp-ocm-oidc-idp`) — the legacy `reconcile/rhidp/ocm_oidc_idp`
integration's own name never had an "rhidp-" prefix (only `sso_client` did). See the
skill's "Naming" lesson for the general rule this established.

## What this integration does (current state, `reconcile/rhidp/ocm_oidc_idp`)

Fully **stateless**, diff-and-apply-in-one-run. No sharding, no early-exit. For each OCM environment:

1. Fetch enabled OCM orgs for this integration from GraphQL (`reconcile/gql_definitions/rhidp/organizations.gql`).
2. Discover RHIDP-labeled clusters directly from OCM (label prefix `sre-capabilities.rhidp`), scoped to those orgs.
3. Interpret cluster labels into `Cluster`/`ClusterAuth` (auth name, issuer, group-filter-regex, status → `oidc_enabled`/`enforced`/`rhidp_enabled`).
4. **Current state**: for each cluster, list existing OCM Identity Providers (`GET /clusters/{id}/identity_providers`).
5. **Desired state**: for each `oidc_enabled` cluster, read the SSO client secret from Vault (written by the sibling `sso_client` integration, path keyed by `org_id-cluster_name-auth_name-issuer_hostname`), validate `issuer` matches, build the desired `OpenIDIdentityProvider` config (client_id/secret/issuer + `claims.groups=["filtered_groups"]` iff a group-filter-regex was configured).
6. **Diff & act**: `diff_iterables` keyed by `(org_id, cluster_name, idp.type, idp.name)`. Delete IDPs not in desired (skip non-matching-name IDPs unless cluster is `enforced`, in which case ALL foreign IDPs are deleted). Add/update only `OpenIDIdentityProvider` type IDPs (never touches Github IDPs beyond classifying/optionally deleting them).

It does **not** create Keycloak clients — that's `sso_client`'s job. The two integrations are coupled only via the Vault secret `sso_client` writes and `ocm_oidc_idp` reads.

Source files: `reconcile/rhidp/ocm_oidc_idp/{integration.py,base.py,metrics.py}`, shared `reconcile/rhidp/common.py` + `reconcile/rhidp/metrics.py`, `reconcile/utils/ocm/identity_providers.py`, `reconcile/utils/ocm/base.py` (IDP models, lines 576-634).

Tests: `reconcile/test/rhidp/{conftest.py,test_common.py,test_ocm_oidc_idp_base.py}`, fixtures `reconcile/test/fixtures/rhidp/clusters.yml` (`get_oidc_idps.yml` appears to be a dead/unreferenced fixture — will not port it).

## Vault secret schema (byte-compatibility contract with `sso_client`)

Path: `{vault_target.path}/{cluster_vault_secret_id}` where `cluster_vault_secret_id = f"{cluster_name}-{org_id}-{auth_name}-{urlparse(issuer_url).hostname}"`.

Value (all 7 fields required, read as a full-secret dict): `client_id, client_name, client_secret, redirect_uris, registration_access_token, registration_client_uri, issuer, attributes`. This is exactly `qontract_api.integrations.sso_client.domain.SsoClientSecret` (already implemented in part 1) and `cluster_vault_secret_id()` (already implemented in `sso_client/domain.py`).

**Known legacy fragility**: today, a malformed/incomplete Vault secret raises an uncaught pydantic `ValidationError` that propagates out of `fetch_desired_state()` and aborts the *entire OCM-environment* iteration, not just the offending cluster (the `try/except` only wraps the Vault *read*, not the `SSOClient(**data)` construction). Flagging as a design decision below.

## What already exists from Part 1 (reuse, do not duplicate)

- `qontract_utils/qontract_utils/ocm_api/` — Layer 1 `OcmApi` (labels/subscriptions/clusters only, **zero IDP methods**), `Filter` DSL, frozen domain models.
- `qontract_api/qontract_api/external/ocm/` — generic `GET /external/ocm/clusters` (label-prefix + org_ids based, `OcmClusterInfo{id,name,organization_id,console_url,external_auth_enabled,labels}`). **Fully reusable as-is** for cluster discovery — no changes needed.
- `qontract_api/qontract_api/integrations/sso_client/` — direct sibling reference for service/router/tasks/domain structure.
- `reconcile/rhidp_api/common.py` — `RHIDP_NAMESPACE_LABEL_KEY`, `STATUS_LABEL_KEY`, `ISSUER_LABEL_KEY`, `AUTH_NAME_LABEL_KEY`, `GROUP_FILTER_REGEX_LABEL_KEY`, `StatusValue`, `get_ocm_environments()`, `get_ocm_orgs_from_env()` — ported from `reconcile/rhidp/common.py`, already covers everything `ocm_oidc_idp`'s client side needs for label constants + GraphQL org lookup. **Reuse directly, no changes needed.**
- Vault `write`/`delete`/`list`/`read_all` support in `SecretManager` — already used the same way by `sso_client`.

## Net-new work required

1. **Layer 1 (`qontract_utils/ocm_api/`)**: OCM Identity Provider CRUD — `_raw_client.py` wire models + methods (`get_identity_providers`, `create_identity_provider`, `update_identity_provider`, `delete_identity_provider`, parameterized by `cluster_id`/`idp_id`, not the `Filter` DSL — IDPs are a per-cluster nested resource, not a global searchable collection). `client.py` `OcmApi` methods wrapping them with `@invoke_with_hooks`. `models.py` frozen domain models (`OcmIdentityProvider` generic + `OcmIdentityProviderGithub` + `OcmIdentityProviderOidc`/`OidcOpenId`/`OidcOpenIdClaims`).
   - **Confirmed no camelCase aliasing needed**: verified `reconcile/utils/ocm/base.py` has no `alias_generator` anywhere in `reconcile/utils/ocm/`, and the legacy code's `by_alias=True` on `model_dump()` is a no-op — OCM's IDP wire format accepts the same snake_case field names as the Python models (`mapping_method`, `open_id`, `client_id`, etc.). New models can mirror this exactly.
2. **Layer 2/3 wiring** for IDP operations (see open decision #2 below).
3. **New integration** `qontract_api/qontract_api/integrations/ocm_oidc_idp/` — `domain.py`, `schemas.py`, `service.py`, `router.py`, `tasks.py`, `metrics.py` (reuse exact Prometheus metric names `rhidp_ocm_oidc_idp_reconcile_errors` / `rhidp_ocm_oidc_idp_reconciled` from legacy `reconcile/rhidp/ocm_oidc_idp/metrics.py` — dashboards key off these).
4. **New client integration** `reconcile/rhidp_api/ocm_oidc_idp/integration.py`, reusing `reconcile/rhidp_api/common.py` as-is. CLI command `rhidp-ocm-oidc-idp-api` registered in `reconcile/cli.py` alongside existing `ocm_oidc_idp` (~line 2980).
5. Tests (server: models/service/router/tasks; client: desired-state compilation + request construction; Layer 1 utils tests for new OCM IDP methods).
6. Docs: `docs/integrations/rhidp-ocm-oidc-idp.md` (mirror `docs/integrations/rhidp-sso-client.md` structure).

## Proposed data model shapes

**Client → server request** (mirrors `SsoClientReconcileRequest`, but note per ADR-002/precedent: *label interpretation stays client-side* — server gets plain booleans, never the `StatusValue` enum or raw labels):

```python
class OcmOidcIdpAuth(BaseModel, frozen=True):
    name: str
    issuer: str
    group_filter_regex: str | None
    oidc_enabled: bool   # replaces StatusValue interpretation - computed client-side
    enforced: bool        # replaces StatusValue interpretation - computed client-side

class OcmOidcIdpCluster(BaseModel, frozen=True):
    cluster_id: str        # OCM cluster id - needed to call IDP endpoints (not name-based)
    name: str
    organization_id: str
    auth: OcmOidcIdpAuth

class OcmOidcIdpReconcileRequest(BaseModel, frozen=True):
    ocm_environment: str
    ocm_url: str
    access_token_url: str
    access_token_client_id: str
    access_token_client_secret: Secret
    clusters: list[OcmOidcIdpCluster]
    vault_target: Secret     # base path where sso_client wrote per-cluster SSO secrets
    dry_run: bool = True
```

(`ocm_url`/access-token fields needed because, unlike `sso_client`, this service must call OCM directly for IDP CRUD — it's not just reading Vault. Mirrors what the `/external/ocm/clusters` endpoint itself takes as query params today.)

**Actions**: `OcmOidcIdpActionCreate{cluster_name, auth_name}` / `OcmOidcIdpActionUpdate{cluster_name, auth_name}` / `OcmOidcIdpActionDelete{cluster_name, idp_name}` — discriminated union on `action_type`, `OcmOidcIdpTaskResult(TaskResult){actions, applied_actions}` — same shape family as `SsoClientAction`/`SsoClientTaskResult`.

**Server-side desired state build** (Layer 3, `service.py`): for each cluster where `auth.oidc_enabled`, read Vault secret at `{vault_target.path}/{cluster_vault_secret_id(...)}`, build desired `OcmIdentityProviderOidc`. This mirrors legacy `fetch_desired_state` but executed server-side (consistent with `sso_client`'s own server-side Vault current-state read — Vault access is not gated behind the "external API" ADR-013 pattern the way OCM/PagerDuty/GitHub are, since `SecretManager` is already a first-class qontract-api capability).

## Design decisions (confirmed)

1. **Shared Vault schema/helper → refactor into a shared rhidp domain layer.** Create `qontract_api/qontract_api/rhidp/domain.py` holding `SsoClientSecret` and `cluster_vault_secret_id()`. Move them out of `qontract_api/qontract_api/integrations/sso_client/domain.py` and update `sso_client`'s imports to point to the new shared location (no behavior change to `sso_client`, pure move + import update). `ocm_oidc_idp/service.py` imports from the same shared module. This touches already-merged `sso_client` code (import path only) but is the architecturally correct home per the skill's shared-model rule.

2. **OCM Identity Provider CRUD gets a full Layer 2 caching workspace client — the read side IS cacheable.** Extend `OcmWorkspaceClient` (`qontract_api/qontract_api/external/ocm/ocm_workspace_client.py`) with:
   - `get_identity_providers(cluster_id) -> list[OcmIdentityProvider...]` — cached (double-checked-locking pattern, same style as `get_clusters`), cache key `f"ocm:idps:{environment_key}:{cluster_id}"`, TTL via new `settings.ocm.identity_providers_cache_ttl`.
   - `create_identity_provider(cluster_id, idp)`, `update_identity_provider(cluster_id, idp_id, idp)`, `delete_identity_provider(cluster_id, idp_id)` — mutations, not cacheable themselves, but **must invalidate** (`cache.delete`) the `get_identity_providers` cache entry for that `cluster_id` after a successful call, so the next read reflects the change instead of serving stale cached state.

3. **Fix the Vault `ValidationError` fragility.** Catch the validation error per-cluster in the server-side desired-state build, log + skip that cluster (same code path as the existing "secret not readable" skip), continue processing the rest. Deliberate improvement over the legacy byte-for-byte behavior, matching `sso_client`'s own per-action error-isolation philosophy.

Phase 1 (Layer 1 OCM IDP client) starts now.

## Phase dependency graph

- Phase 1 (Layer 1 OCM IDP methods in `qontract_utils`) → prerequisite for Phase 2.
- Phase 2 (server-side: domain/schemas/service/router/tasks/metrics) → prerequisite for Phase 4 (client-side) via OpenAPI regen. No new Phase 3 (external endpoints) needed — cluster discovery reuses the existing `/external/ocm/clusters` endpoint as-is.
- Phase 4 (client-side `reconcile/rhidp_api/ocm_oidc_idp/`) depends on Phase 2 + client regen.
- Phase 5 (tests) overlaps with 1/2/4 as they're written.
- Phase 6 (docs + skill update) last.

## Resumption context (after `/clear`)

Read this file in full, plus:
- `qontract_api/qontract_api/integrations/sso_client/{domain.py,schemas.py,service.py,router.py,tasks.py,keycloak_client_factory.py}` — structural template.
- `qontract_utils/qontract_utils/ocm_api/{client.py,_raw_client.py,models.py}` — Layer 1 extension point.
- `qontract_api/qontract_api/external/ocm/ocm_workspace_client.py` — Layer 2 extension point (if Option A chosen for decision #2).
- `reconcile/rhidp/ocm_oidc_idp/base.py`, `reconcile/rhidp/common.py`, `reconcile/utils/ocm/identity_providers.py`, `reconcile/utils/ocm/base.py` (lines 576-634) — legacy logic being ported.
- `reconcile/rhidp_api/{common.py,sso_client/integration.py}` — client-side template.
