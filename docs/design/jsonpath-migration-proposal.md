# Replace jsonpath-ng with python-jsonpath

## Problem

This is recurring upgrade work, not a hypothetical compatibility concern:

- **August 2026:** `jsonpath-ng` 1.8.0 changed how paths were displayed, making
  change-owner reports difficult to read. Commit `7eba2054` added a dedicated
  compatibility fix.
- **November 4–5:** the dependency update attempted **1.8.0 → 1.15.0**. Stricter
  JSONPath-standard behavior changed string indexing and wildcard handling of
  dictionaries and scalars. Existing Jinja filters could return different results
  without raising errors. New type information also exposed incompatible
  assumptions in change coverage and promotion code.
- Preserving existing behavior required an initial compatibility patch followed
  by **five further commits**. Review repeatedly found cases the fixes missed:
  nested paths, filters, Boolean expressions, and arithmetic expressions.
- Testing **1.16.0** then broke the compatibility layer again because wildcard
  representation changed, producing **10 failing tests**. The upgrade was
  abandoned for that dependency update: commit `0e0b22d7` restored **1.8.0** and
  removed the compatibility patches. The merged update (`3285ad1e`) retained
  that pin; these failures were caught before shipping the new version.

`jsonpath-ng` is maintained, but our code also depends on its parser nodes for
paths and change coverage. Routine upgrades therefore combine query migration
with repairs to library-specific code. The proposal addresses both problems:
adapt queries deliberately and remove that coupling. The replacement still has
additional syntax differences; the two engines are not interchangeable.

## Why python-jsonpath

- **Maintained:** verified repository commits in October 2026.
- **Documented API:** typed query results expose values, concrete locations, and
  JSON Pointers without requiring consumers to manipulate parser nodes.
- **Clearer upgrade boundary:** version 2.0 explicitly documented breaking changes
  as a major release. Future updates still need behavioral tests.
- **No mandatory runtime dependencies or native extensions.**

It is not universally faster or a drop-in replacement. Cached evaluation was
roughly twice as slow in representative microbenchmarks, adding about 1–5 ms per
1,000-record query. Temporary dual-engine comparison adds further overhead, which
must be measured in integration-level checks.

## Proposed qontract_utils package

Introduce a shared `qontract_utils.jsonpath` package for queries, match locations,
and updates. It owns both engines during migration and presents one consistent
interface to integrations. Consumers no longer depend on either library's parser
nodes. Engine selection stays inside the utility; reconcile gains no new setting.
Existing Jinja filter names remain unchanged.

The package must detect **both syntax failures and silent result differences**.
During migration it compares match values, types, locations, order, and duplicates
on isolated input copies, without replaying mutations. Differences are logged to
CloudWatch, not Slack. M1 always keeps `jsonpath-ng` results; M2 uses `jsonpath-ng` for unapproved
differences before updates are applied.

## Affected integrations

| Area                     | Integrations and affected behavior                                                                                                                                                                                                                                           |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Authorization            | `change-owners`, `change-log-tracking`: change coverage and ownership.                                                                                                                                                                                                       |
| SaaS                     | `openshift-saas-deploy`, its change tester and config/image/moving-commit/upstream-job triggers, `saas-file-validator`, `saas-auto-promotions-manager`, `dashdotdb-dora`: namespace selection and templated parameters.                                                      |
| Rendering and validation | `openshift-resources`, `openshift-prometheus-rules`, `template-renderer`, `template-validator`, `resource-template-tester`, `prometheus-rules-tester`, `query-validator`.                                                                                                    |
| Other template consumers | `terraform-resources`, `external-resources`, `fleet-labeler`, `ocm-upgrade-scheduler-org-updater`: configured secret, cloud-init, label, or policy templates.                                                                                                                |
| Sharding                 | `terraform-users`, `terraform-resources`, `terraform-tgw-attachments`, `terraform-vpc-resources`, `openshift-resources`, `openshift-vault-secrets`, `openshift-rhcs-certs`, `openshift-managed-sso-client-secrets`, `prometheus-rules-tester`, `jira-permissions-validator`. |
| Status and promotions    | `status-board-exporter`: application selection; `gitlab-mr-sqs-consumer`: component-promotion updates.                                                                                                                                                                       |

Template-related impact depends on configured expressions. Ordinary tenant SaaS
templates processed by OpenShift or Helm do not receive our custom Jinja filters.

## Existing query incompatibilities

The local audit found **385 distinct expressions; 79 fail target parsing**,
including templates, fixtures, and documentation. There are two kinds of problem:

**Syntax changes:** some existing queries must be rewritten before Python can
evaluate them. These examples preserve results on representative inputs:

| Existing query                                             | Replacement                                                 | Reason                                       |
| ---------------------------------------------------------- | ----------------------------------------------------------- | -------------------------------------------- |
| `roles[*].'$ref'`                                          | `roles[*]['$ref']`                                          | Quoted field names require bracket notation. |
| `namespace[?(@.name=="api" & @.environment.name=="prod")]` | `namespace[?(@.name=="api" && @.environment.name=="prod")]` | Use `&&` for logical AND.                    |
| `resourceTemplates[?name=="api"].targets`                  | `resourceTemplates[?@.name=="api"].targets`                 | `@` identifies the object being filtered.    |

**Silent behavior changes:** a query may parse successfully but select different
data. Results below were verified with `jsonpath-ng==1.8.0` and
`python-jsonpath==2.2.2`:

| Query and input                                                     | `jsonpath-ng` 1.8.0 result | python-jsonpath result                                               |
| ------------------------------------------------------------------- | -------------------------- | -------------------------------------------------------------------- |
| `$.name[0]` on `{"name":"api"}`                                     | `["a"]`                    | `[]`: strings are not arrays.                                        |
| `$.items[*]` on `{"items":{"name":"api"}}`                          | `[{"name":"api"}]`         | `["api"]`: the wildcard selects object values, not the whole object. |
| `$[?@.v==1].v` on `[{"v":"1"},{"v":1},{"v":true}]`                  | `["1",1,true]`             | `[1]`: no string-to-number or Boolean-to-number equality.            |
| `items[?(@.name =~ "api")].name` on `{"items":[{"name":"my-api"}]}` | `["my-api"]`               | `[]`, despite successful parsing.                                    |

For the regex example, use `items[?search(@.name, "api")].name` to retain substring
matching; it returns `["my-api"]`. Using a full-match operation instead would
change the selection again.

The scalar, wildcard, and comparison changes also occur when upgrading `jsonpath-ng` toward
RFC 9535 behavior. They are not all costs introduced by replacing the library.
Syntax checks alone would miss these examples, so M1 must also compare actual
query results inside the shared package. Queries and their generators must be
adapted together, with expected-result tests rather than blind text replacements.

**Keeping jsonpath-ng does not avoid adapting our queries.** Versions 1.15 and
1.16 already incorporate changes toward **RFC 9535**, the JSONPath standard:
stricter scalar/wildcard behavior, distinct numeric and Boolean comparisons, and
deprecation of single `&` in favor of `&&`. Queries and templates that depend on
1.8.0 behavior need changes even if we upgrade `jsonpath-ng` rather than replace it; the
alternative is maintaining compatibility patches indefinitely.

## Milestones

### M1 — Introduce the package, migrate consumers, and observe

- Add `qontract_utils.jsonpath` with both libraries. Keep `jsonpath-ng==1.8.0`
  as the default; engine selection is available only inside the utility.
- Adapt affected reconcile integrations, shared helpers, and Jinja filters to
  use the package instead of either library directly. Deliver these changes in
  small, behavior-preserving PRs.
- Let the package validate syntax and compare results between engines without
  changing `jsonpath-ng` behavior. Send incompatibility diagnostics to CloudWatch, not Slack.

**Complete when:** all affected query paths use the package and tests confirm
unchanged authorization, deployment selection, sharding, and rendered output.

### M2 — Adapt queries and switch the package default

- After several weeks or months, use the logs to update queries in app-interface
  and reconcile, including generators and fixtures, in small tested batches.
- Change the package default to `python-jsonpath`. Keep `jsonpath-ng` as a logged fallback
  for incompatible queries and unapproved result differences. Reconcile continues
  using the same package interface, without engine-specific settings.
- Continue fixing observed incompatibilities and checking rarely used queries.

**Complete when:** representative workloads no longer require fallback and all
remaining inventory entries and behavior differences have been reviewed.

### M3 — Remove the legacy engine

- Remove `jsonpath-ng`, its fallback, and temporary dual-engine comparison from the utility
  package and dependencies. Keep the shared interface and regression tests.
- Verify reconcile works with `python-jsonpath` alone before releasing cleanup.

## Risks and safeguards

- Changed matches could grant unintended permissions, select the wrong deployment
  targets, or miss affected shards. Verify decisions and outputs, not just syntax.
- Compare real results before choosing fallback: two empty results agree, while
  an empty/nonempty difference needs review. Never replay mutations.
- Quiet logs do not prove unused configurations are safe. Include rare jobs,
  generated queries, unavailable comparisons, and static inventory before removing `jsonpath-ng`.
- Keep each milestone independently deployable and retain a compatible rollback.

## Scope

**In scope:** the shared package, its consumers, affected app-interface queries
and generators, compatibility diagnostics, tests, and staged removal of `jsonpath-ng`.

**Out of scope:** unrelated integration refactoring, migration to qontract-api,
intentional permission changes, Kubernetes CLI JSONPath, tenant Helm/OpenShift
template engines, and permanent support for two JSONPath libraries.
