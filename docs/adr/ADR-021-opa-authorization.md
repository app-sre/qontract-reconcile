# ADR-021: OPA-Based Authorization for qontract-api

## Status

Selected

## Context

qontract-api centralizes external API calls for reconcile integrations (ADR-013). Integrations pass Vault paths and external service URLs as request parameters. qontract-api resolves secrets and connects to the specified services.

The problem: **any caller with a valid JWT can provide arbitrary parameters.** This enables two attack vectors:

1. **Arbitrary Vault secret reads** — attacker specifies any Vault path; the secret is used in subsequent operations
2. **Credential exfiltration via SSRF** — attacker provides their own server URL alongside a Vault path; qontract-api resolves the secret and sends it to the attacker-controlled server

## Decision

Deploy OPA (Open Policy Agent) as a sidecar alongside qontract-api, following the proven pattern from [automated-actions](https://github.com/app-sre/automated-actions/tree/main/packages/opa).

### How it works

1. Every authenticated request is checked against OPA before reaching the endpoint handler
2. qontract-api sends an input document to OPA: `{username, obj (operation_id), params (flattened)}`
3. OPA evaluates the request against role-based policies with regex parameter matching
4. Denied requests get HTTP 403; OPA errors also result in 403 (fail-closed)

### Key design choices

- **Integrated into `UserDep`** — authorization runs as part of the existing `get_current_user` dependency chain (`_authenticate` → `_authorize`). No separate `AuthZDep` needed; every endpoint using `UserDep` is automatically protected.
- **Fail-closed** — any OPA error (timeout, connection, invalid response) denies the request with HTTP 403, not 500.
- **HTTP 403 for authZ failures** — distinguished from HTTP 401 (authentication failures).
- **Connection pooling** — single `httpx.AsyncClient` with keep-alive connections to the OPA sidecar.
- **POST body flattening** — nested request bodies are flattened to dot-notation (e.g., `secret.path`) for uniform OPA regex matching.
- **Parameter collection for all HTTP methods** — path params, query params, and body are collected regardless of HTTP method.
- **Reused Rego policies** — identical `rbac.rego` and `user.rego` from automated-actions, same input document format and policy data structure.
- **No rate limiting in OPA** — qontract-api uses its own token bucket rate limiting.

### Observability

- `qontract_api_opa_decision_duration_seconds` histogram — tracks OPA call latency
- `qontract_api_opa_decisions_total` counter (labels: `result`, `obj`) — tracks allow/deny/error rates
- Audit logging on denials with structlog (username, operation, params)
- OPA included in `/health/ready` readiness probe

## Alternatives Considered

### Static allowlists in qontract-api config

Discarded: not per-subject, not scalable, changes require redeployment.

### Named service references (eliminate URLs from API)

Discarded: contradicts ADR-013 (qontract-api should not own service configs), breaking API change.

### JWT token scoping

Discarded: requires token re-issuance on policy changes, OPA provides the same with hot-reloadable policies.

## References

- [Design doc](https://github.com/openshift-online/platform-engineering-enhancements/pull/51)
- [ADR-013: Centralize external API calls](./ADR-013-centralize-external-api-calls-in-api-gateway.md)
- [automated-actions OPA implementation](https://github.com/app-sre/automated-actions/tree/main/packages/opa)
- [APPSRE-14303](https://issues.redhat.com/browse/APPSRE-14303)
