# ADR-021: Vault Secret Deletion Guardrails

**Status:** Proposed
**Date:** 2026-06-02
**Authors:** Tyler Pate

## Context

On 2026-06-02, a Vault KV v2 secret (`hcc/jira-ai-categorizer`, version 2) was deleted from Vault while still referenced by a namespace configuration in app-interface. This caused the `openshift-vault-secrets` integration to fail with:

```
[hcmaii01ue1/jira-ai-categorizer] error fetching secret: version '2' not found for secret with path 'hcc/jira-ai-categorizer'
```

The integration correctly treated this as an error — Vault returned HTTP 404 for the destroyed version, `VaultClient.__read_all_v2` raised `SecretVersionNotFoundError`, and the integration exited non-zero. This is the expected behavior when a declared dependency is missing. The existing safety mechanism of disabling cluster deletions on error (`options.enable_deletion = not ri.has_error_registered()`) prevented any damage to running workloads — the existing K8s Secrets remained untouched.

However, the CI failure blocked all subsequent qontract-reconcile promotions that triggered the `openshift-vault-secrets` dry-run, requiring a force-merge of MR !190766 to unblock.

The root cause is that Vault is an external mutable store with no awareness of app-interface's declarative references. Nothing prevents a user from deleting a secret version that is actively depended upon — it is a "rug pull" on a declared dependency in a gitops repository.

### Current behavior

- **KV v2 versioned secrets are treated as immutable** by convention, but Vault RBAC does not enforce this. Any user with `delete` or `destroy` capability on a path can remove versions.
- **`VaultClient.delete()` already refuses v2 deletions** (raises `ValueError("deleting V2 secrets is not supported yet")`), demonstrating that the codebase already treats v2 versions as immutable. But this only governs qontract-reconcile's own write path, not external Vault users.
- **Deletions bypass the gitops workflow entirely.** App-interface enforces review and CI checks for all configuration changes, but Vault deletions happen outside this process — there is no MR, no review, and no validation that the secret is still in use.

### Requirements

- Vault secret deletions must go through the gitops workflow: remove the app-interface reference first, then delete from Vault
- Maintain the ability for teams to migrate secrets between Vault engines (with proper coordination)
- Keep the solution simple — avoid background integrations when the problem can be prevented at the source

## Decision

Enforce Vault KV v2 secret immutability through RBAC policy changes, and route all secret deletions through app-interface and a dedicated integration or privileged role. This brings secret lifecycle management under the same gitops workflow as every other infrastructure change.

### Key Points

- **Remove `delete` and `destroy` capabilities** from standard team Vault policies on KV v2 mounts. Add explicit `deny` rules to prevent escalation.
- **Route deletions through app-interface.** To delete a secret: first remove the reference in app-interface (standard MR with review and CI checks), then delete from Vault using either a dedicated `vault-delete-secret` integration or a privileged role with an approval workflow.
- **Improve error messages** in `openshift_resources_base.py` to include remediation guidance when a secret version is missing, making the failure actionable.

## Alternatives Considered

### Alternative 1: RBAC + Gitops-Routed Deletion *(Selected)*

Remove `delete`/`destroy` from standard Vault policies. Secret deletion requires removing the app-interface reference first (MR + CI), then either a `vault-delete-secret` integration reconciles the actual Vault deletion, or a privileged role is used through an approval workflow.

**Pros:**

- Prevents the problem at the source — no one can delete what they shouldn't
- Follows the existing gitops pattern — all changes go through app-interface with review
- Simple — no new background integrations polling Vault
- The `vault-delete-secret` integration (or privileged role) ensures the correct order of operations: remove consumer, then remove resource
- `VaultClient.delete()` already refuses v2 deletions, so the codebase convention and RBAC align

**Cons:**

- Teams can no longer self-service delete KV v2 secret versions directly in Vault
  - **Mitigation:** The gitops workflow is the standard path for all other infrastructure changes. Secret deletion should be no different.
- Requires coordination with Vault administrators for the initial RBAC change
  - **Mitigation:** This is a one-time configuration change, not an ongoing operational burden.

### Alternative 2: Background Validator Integration

A scheduled integration that scans all `vault-secret` references and verifies each `(path, version)` exists in Vault, alerting on mismatches.

**Pros:**

- Catches orphaned references regardless of how deletion happened

**Cons:**

- Reactive, not preventive — the deletion still happens, the validator just detects the mess afterward
- Unnecessary complexity if RBAC prevents the deletion in the first place
- Adds operational overhead (new integration to maintain, Vault read load)
- Does not enforce the correct order of operations

### Alternative 3: Early-Exit Enhancement to Include Vault Probing

Modify the `openshift-vault-secrets` early-exit hash to include Vault version existence checks.

**Pros:**

- Catches the exact scenario from this incident during CI

**Cons:**

- Adds Vault API calls to every early-exit check, increasing latency and Vault load
- Early-exit is a performance optimization; adding external calls defeats its purpose
- Still reactive — only catches issues when an MR triggers the integration
- Does not prevent the deletion

### Alternative 4: Layered Defense — RBAC + Background Validator + Error Handling

Combine RBAC restriction, a background validator integration, and improved error handling.

**Pros:**

- Defense in depth — multiple layers

**Cons:**

- Over-engineered if RBAC is properly enforced — the background validator adds complexity with marginal benefit
- The correct approach is to prevent the problem, not build elaborate detection for a preventable failure mode

## Consequences

### Positive

- Vault KV v2 secret versions become effectively immutable, matching the existing codebase convention (`VaultClient.delete()` already refuses v2)
- Secret deletions follow the same gitops workflow as all other infrastructure changes — MR, review, CI checks
- The correct order of operations is enforced: remove the consumer (app-interface reference) before removing the resource (Vault secret)
- CI pipeline failures from externally deleted secrets are eliminated
- Teams retain the ability to migrate secrets through a controlled, auditable process

### Negative

- Teams can no longer self-service delete KV v2 secret versions directly in Vault
  - **Mitigation:** Provide a `vault-delete-secret` integration or privileged role that handles Vault deletion after app-interface references are removed. Write a runbook documenting the migration workflow.
- Vault RBAC changes require coordination with Vault administrators
  - **Mitigation:** Propose as a standard Vault configuration. The change is simple — remove capabilities and add deny rules.

## Implementation Guidelines

### Vault RBAC Policy

Remove `delete` and `destroy` capabilities from standard team policies on KV v2 mounts.

**Current typical policy:**

```hcl
path "hcc/data/*" {
  capabilities = ["create", "read", "update", "delete", "list"]
}

path "hcc/metadata/*" {
  capabilities = ["read", "list", "delete"]
}
```

**Proposed policy:**

```hcl
path "hcc/data/*" {
  capabilities = ["create", "read", "update", "list"]
}

path "hcc/metadata/*" {
  capabilities = ["read", "list"]
}

# Deny version destruction explicitly
path "hcc/destroy/*" {
  capabilities = ["deny"]
}

path "hcc/delete/*" {
  capabilities = ["deny"]
}
```

### Controlled Deletion Path

Two options for the controlled deletion path (not mutually exclusive):

**Option A: `vault-delete-secret` integration**

A new integration that reconciles Vault secret deletions declared in app-interface. Teams add a deletion marker to the namespace config (or a dedicated deletion resource), the MR goes through standard review and CI, and the integration performs the actual Vault deletion after merge.

**Option B: Privileged role with approval workflow**

A `vault-secret-admin` policy retains `delete`/`destroy` capabilities. Access requires an approval workflow (e.g., via app-interface role request). Teams use this role for one-off migrations after removing app-interface references.

```hcl
# vault-secret-admin policy (restricted access)
path "+/delete/*" {
  capabilities = ["update"]
}

path "+/destroy/*" {
  capabilities = ["update"]
}
```

### Improved Error Messages

Enhance `SecretVersionNotFoundError` handling in `openshift_resources_base.py` to include remediation guidance:

```python
except SecretVersionNotFoundError as e:
    msg = (
        f"Vault secret version deleted or missing: {e}. "
        f"This typically means the secret version was destroyed in Vault "
        f"while still referenced in app-interface. "
        f"Remediation: update or remove the reference in the namespace config."
    )
    raise FetchSecretError(msg) from None
```

### Checklist

- [ ] Draft Vault RBAC policy change proposal for Vault administrators
- [ ] Get approval for RBAC policy change from platform team
- [ ] Apply `deny` rules for `delete`/`destroy` on KV v2 mounts
- [ ] Create `vault-secret-admin` privileged policy with approval workflow
- [ ] Decide on controlled deletion path (integration vs. privileged role vs. both)
- [ ] Improve error messages in `openshift_resources_base.py`
- [ ] Write secret migration runbook for teams
- [ ] Document the immutability contract for KV v2 secrets in `docs/patterns/secret-management.md`

## References

- Related ADRs: ADR-011 (Dependency Injection), ADR-013 (Centralize External API Calls), ADR-017 (Factory Pattern)
- Implementation: `reconcile/utils/vault.py`, `reconcile/openshift_resources_base.py`
- Pattern: `docs/patterns/secret-management.md`
- Incident: Slack thread 2026-06-02, MR !190766

---

## Notes

This ADR was prompted by a production incident where a legitimate team action (migrating a secret to a different Vault engine for least-privilege access) had an outsized blast radius due to missing guardrails. The goal is not to prevent secret migration — it is to ensure that migrations follow the same gitops workflow as every other infrastructure change.

The `VaultClient.delete()` method in `reconcile/utils/vault.py` already refuses to delete KV v2 secrets (`ValueError("deleting V2 secrets is not supported yet")`). This ADR extends that same principle to Vault RBAC: if the codebase treats v2 versions as immutable, so should the Vault policies.
