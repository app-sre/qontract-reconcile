# Migration plan: jsonpath-ng to python-jsonpath

Date: 2026-11-05

Ticket: <https://redhat.atlassian.net/browse/APPSRE-15715>

Status: Implementation plan for later execution. No application or app-interface
configuration changes have been made by this planning task.

## Milestones at a glance

The overall goal is unchanged, but the migration is **observe, migrate, remove**,
not a single engine/configuration cutover. Each substep below is a separately
reviewable, deployable change with its own tests.

| Milestone                     | Authoritative engine                                                          | Other engine                                                                                  | Configuration policy                                                                                                                |
| ----------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **M1: introduce and observe** | `jsonpath-ng==1.8.0`                                                          | `python-jsonpath==2.2.2` validates syntax and compares query results on isolated input copies | No required syntax or authoritative behavior changes. Collect syntax and semantic diagnostics in CloudWatch, not Slack.             |
| **M2: migrate gradually**     | Initially `jsonpath-ng`; then change the utility default to `python-jsonpath` | Retain `jsonpath-ng` as an explicit, observable fallback                                      | After weeks/months of evidence, migrate queries in small batches and continue fixing fallback cases.                                |
| **M3: remove jsonpath-ng**    | `python-jsonpath`                                                             | None                                                                                          | Remove `jsonpath-ng` only after fallback is unused across representative workloads and remaining static/dynamic cases are resolved. |

Engine selection is a **qontract_utils-only parameter**. Reconcile consumers use
the utility's default; do not add an integration argument, environment variable,
Helm value, app-interface field, or per-consumer engine setting.

M1 validation failures must not change `jsonpath-ng` results, mutations, exit status, early
exit, or Slack notifications. M2 fallback must be visible in CloudWatch rather
than silently hiding migration work. M3 is a separate cleanup release, not part
of changing the default in M2.

**The package must detect silent behavior changes, not just invalid syntax.**
Whenever a query is evaluated during M1/M2, compare both engines' complete match
results for that input when both can evaluate it. M1 always returns `jsonpath-ng` results;
M2 falls back to `jsonpath-ng` for an unapproved observed difference before any mutation.
Log mismatches to CloudWatch only. Observed parity is evidence for that input,
not proof for every possible input; retain the inventory and regression tests.

## 1. Decision, motivation, and scope

Replace **`jsonpath-ng==1.8.0` with `python-jsonpath==2.2.2`**, behind a small
project-owned abstraction. The distribution is `python-jsonpath`; its Python
import is `jsonpath`. Do not accidentally install `jsonpath-python`, which uses
the same import namespace but is a different project.

The motivation is to stop repeatedly repairing application behavior when `jsonpath-ng`'s
parser, AST, rendering, and compliance behavior change. Merely replacing imports
would reproduce that coupling with another library.

The user prefers the maintained, typed, dependency-free `python-jsonpath` API over
the faster `jsonpath-rfc9535` alternative. Cached evaluation of three 1,000-record
microbenchmarks cost about 1-5 additional milliseconds per call. Accept that
tradeoff unless representative integration measurements demonstrate a problem.
Preserve bounded compilation caching; do not add a native engine or distributed
cache for this migration.

Those timings exclude the temporary M1/M2 comparison and input-copying costs.
Measure the full comparison path before rollout; do not present parser or
single-engine timings as the migration's total overhead.

Related documents:

- [Complete app-interface query inventory](app-interface-jsonpath-inventory.md).
- [Original package evaluation](jsonpath-replacement-evaluation.md), retained as
  research history; this plan supersedes its original package recommendation and
  its overly broad assumption about unknown tenant template consumers.

### In scope

- A reusable query/location/mutation boundary in `qontract_utils`.
- All `jsonpath-ng`/helper consumers in `reconcile`, including change-owner authorization,
  desired-state sharding, Jinja filters, namespace selection, template patching,
  and promotion mutations.
- Required expression changes in app-interface data, resources, generators,
  fixtures, and documentation.
- Characterization, differential tests, package checks, representative dry-runs,
  coordinated rollout, and rollback.

### Not in scope

- Migrating integrations to qontract-api or changing unrelated membership,
  authorization, early-exit, diff, or cleanup policies.
- Writing a general legacy JSONPath interpreter or indefinitely retaining two
  production engines. Keeping both pinned engines through M1/M2 is intentional.
- Renaming the existing Jinja filter names or adding v2 filters by default.
- Replacing Kubernetes CLI JSONPath, Helm, OpenShift template processing,
  `jsonpatch`, or `jsonpointer` elsewhere in the project.
- Manual edits to generated GraphQL classes or generated API clients.

## 2. Verified exposure and inventory baseline

The custom filters are installed by
`reconcile/utils/jinja2/utils.py:compile_jinja2_template` and are available to all
callers of that shared environment, not just two providers.

| Rendering surface                                                       | Where its template/configuration comes from        | Migration action                                                                                          |
| ----------------------------------------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| OpenShift `resource-template`, including extra-curly variants           | app-interface resources                            | Audit resource bodies and variables; preserve rendered Kubernetes objects.                                |
| Prometheus resource templates and templated tests                       | app-interface resources/test definitions           | Audit and run existing template and Prometheus tests.                                                     |
| Template mechanism: bodies, conditions, paths, static/dynamic variables | app-interface template collections and definitions | Update GABI condition, patch selectors, generators, and expected output.                                  |
| SaaS target parameters and secret field/path interpolation              | app-interface SaaS configuration                   | Audit strings rendered by `resolve_templated_parameters`.                                                 |
| External-resource output formatting and Terraform secret formatting     | app-interface configuration                        | Audit `output_format.data` and `secret_format` templates.                                                 |
| ASG cloud-init templates                                                | resources fetched from app-interface GraphQL       | Audit resource bodies rendered with the extra-curly environment.                                          |
| Fleet subscription labels and upgrade-policy templates                  | app-interface resource references/configuration    | Audit and run their existing tests.                                                                       |
| Tenant SaaS OpenShift templates, directories, Helm charts               | tenant repositories                                | These use `oc process`, YAML loading, or Helm, not this custom Jinja environment; do not assume exposure. |

`github()` returns fetched content as data; it does not recursively render that
content with the custom filters. Dynamic JSONPath strings remain possible within
the controlled rendering surfaces, so template tests must exercise actual inputs.

### Inventory delivered with this plan

The inventory reads current working-tree configuration at app-interface HEAD
`525a2b1ee2717889e0e23336fe80276ac58ea7b0` and records every extracted query with
source file, line, indexed field, source kind, and a query-catalog ID.

- **1,020 occurrences / 385 distinct source expressions / 243 files** when
  including documentation examples, embedded expected YAML, and generator text.
- The previously counted **987 structured occurrences / 381 expressions / 232
  files** are the narrower configuration/fixture subset, not a conflicting count.
- **79 distinct expressions fail target parsing as written.**
- **90 candidate rewrites compile**, including legacy quoted-regex expressions
  that the target parses but evaluates differently. This is syntax evidence only.
- **One root-reset expression requires a deliberate semantic decision.**
- **One dynamic Jinja filter call** was found in the local snapshot, in GABI.
- Five HCP generator bodies contain Jinja control flow that prevents plain YAML
  parsing; their selector lines were recovered textually and must be rendered.
- Raw-text references and unrelated Kubernetes CLI JSONPath are separately listed.

| Category                                                      | Occurrences | Distinct expressions | Target parse failures |
| ------------------------------------------------------------- | ----------: | -------------------: | --------------------: |
| Change-type selectors, including documentation examples       |         462 |                  291 |                    13 |
| Ownership-context selectors, including documentation examples |          86 |                   33 |                    21 |
| Implicit ownership, including documentation example           |           6 |                    5 |                     4 |
| Namespace selectors, generators, and expected outputs         |         386 |                   24 |                    24 |
| Status-board selectors                                        |           2 |                    1 |                     0 |
| Template patch paths                                          |          66 |                   33 |                    18 |
| Template patch JSONPath identifiers                           |          12 |                    4 |                     0 |

Distinct expressions overlap between categories. All extracted source expressions
parsed with `jsonpath-ng` 1.8.0. Parsing acceptance is not behavioral equivalence. Refresh
the inventory before implementation if either checkout has changed.

## 3. Target abstraction

### Placement and dependency ownership

Introduce a small package, keeping vendor adapters private:

```text
qontract_utils/qontract_utils/jsonpath/
  __init__.py       # empty
  domain.py         # project-owned match/location models and engine enum
  query.py          # default facade, engine parameter, validation and fallback
  _comparison.py    # isolated result comparison and typed mismatch outcomes
  _jsonpath_ng.py    # private jsonpath-ng 1.8.0 adapter
  _python.py        # private python-jsonpath adapter
qontract_utils/tests/jsonpath/
```

Only private adapters import their vendor's query/match/AST types. Consumers
import project types/functions, never vendor selectors, matches, or exceptions.
The package imports no `reconcile`, `qontract_api`, or generated GraphQL models.
Import from the defining modules; do not create a barrel re-export.

In M1, declare **both** `jsonpath-ng==1.8.0` and `python-jsonpath==2.2.2` in
`qontract_utils/pyproject.toml` and regenerate the lockfile without unrelated
upgrades. Remove the root's redundant `jsonpath-ng` declaration only after direct imports
have moved behind the package. Keep the `jsonpath-ng` version fixed throughout M1/M2.
Remove `jsonpath-ng` from the utility dependency list in **M3**, not in M2. Do not introduce
the `strict` extra or another JSONPath distribution.

### Utility-only engine switch

Proposed library contract: a `JsonPath` facade accepts a keyword-only `engine`
parameter using a `JsonPathEngine` enum. Omitting it resolves the utility's
current default. The module-level `compile_query(expression)` uses a default
facade internally; **all reconcile call sites omit engine selection**.

- M1 default: `jsonpath-ng`. Explicit Python selection is available to utility tests and
  controlled comparisons, not surfaced through reconcile configuration.
- M2: change the utility default to Python while retaining the `jsonpath-ng` fallback policy.
- M3: remove the `jsonpath-ng` enum option/adapter/fallback once no callers need it.
- Cache keys include the resolved primary engine, fallback policy, and expression;
  do not let cached `jsonpath-ng` queries survive a default change in tests. Deployments pick
  up a default change through the utility release/process restart.

The engine parameter is an internal library capability, not a migration control
to be threaded through every integration. Do not introduce a plugin framework.

This follows the shared-library direction of ADR-007 and the typed-model rules
of ADR-012. This task is a dependency migration, not qontract-api integration
development; changing existing reconcile consumers is necessary and in scope.

### Public concepts

Use frozen Pydantic models for application-owned metadata. Data being selected
is genuinely dynamic JSON/YAML; carry its values as `object`, not an arbitrary
dictionary schema and not a reconstructed Pydantic copy.

| Concept                             | Contract                                                                                                                                                                                           |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `JsonLocation`                      | Hashable, strictly validated tuple of string field names and integer indexes. Empty tuple is root. Booleans are not accepted as indexes; numeric strings remain field names.                       |
| `JsonMatch`                         | `location: JsonLocation`, `value: object`. Mutable values refer to the original document; no deep copy or JSON round trip. Frozen metadata does not imply deep immutability of the selected value. |
| `JsonQuery`                         | Small `Protocol` exposing `find(data) -> list[JsonMatch]`; a private implementation wraps a compiled upstream query. No public AST.                                                                |
| `compile_query(expression)`         | Bounded LRU of compiled project query wrappers, initially capacity 256. No result/data caching.                                                                                                    |
| `lookup_at(data, location)`         | Return `JsonMatch` or `None`; distinguish missing from an existing JSON null.                                                                                                                      |
| `replace_at(data, location, value)` | Mutate a non-root mapping/list entry in place; return `None`. Explicitly handle root replacement at the caller.                                                                                    |
| `delete_at(data, location)`         | Remove a non-root entry in place; return `None`. List indexes are resolved against the current document.                                                                                           |
| Stable project exceptions           | Separate syntax, evaluation, and mutation failures; translate typed upstream failures at the boundary. Do not turn malformed queries into empty matches.                                           |

`JsonLocation` needs structural equality, `parent`, `is_prefix_of`, `relative_to`,
joining, a deterministic display formatter, and RFC 6901 pointer rendering.
`relative_to` must distinguish an unrelated path (`None`) from the valid empty
relative path when both locations are equal. Do not use truthiness to confuse
those cases. Equality and dictionary keys must not rely on display strings.

Example of the boundary, expressed as data rather than an implementation:

```text
Query:       $.resourceTemplates[*].targets[*].ref
Match path:  ("resourceTemplates", 0, "targets", 2, "ref")
Pointer:     /resourceTemplates/0/targets/2/ref
Display:     resourceTemplates.[0].targets.[2].ref
```

### Implementation constraints and edge cases

1. Use a private, explicitly configured `JSONPathEnvironment(strict=False,
   well_typed=True)`. This preserves target support for rootless paths and
   hyphenated shorthand names; do not accidentally enable strict RFC parsing.
2. Prefer the RFC-style syntax subset for changed configuration, but do not
   rewrite already compatible queries merely to add `$` or canonical brackets.
3. Adapt public match `parts` into `JsonLocation`. Validate that ordinary
   location-bearing queries produce only real field/index components; do not
   silently accept artificial pseudo-root or key-selector locations as real data.
4. Upstream treats string `data` as serialized JSON. For Python scalar input,
   pass its JSON encoding so `"123"` stays a string and `'{"a":1}'` stays a
   string rather than becoming an object. This public-API strategy was verified.
   Pass mappings/sequences directly to preserve ruamel objects and references.
5. Do not serialize mapping/list input to bypass type checking; that loses
   identity, YAML comments, tags, and potentially native value types.
6. Preserve duplicate matches and ordering for queries. Deduplicate concrete
   locations only where existing business logic already treats them as a set.
7. Normalize negative array indexes in match locations; test numeric-looking
   mapping keys, empty names, dots, slashes, tildes, quotes, Unicode, and backslashes.
8. Root replacement/deletion cannot be implemented as ordinary parent mutation.
   Characterize existing root callers and handle them explicitly, rather than
   adding a mutation function that sometimes returns a new root and sometimes
   mutates its argument. Do not silently repair unrelated root behavior.
9. Compile and evaluate concurrently in tests. Retain no document-specific state
   in cached wrappers; one data set must not affect a later or parallel evaluation.
10. Compiled wrappers stay process-local. Only concrete location/diff data crosses
    the existing multiprocessing boundary; verify pickle round trips.
11. Test regex behavior both with and without optional regex packages available,
    including the actual workspace dependency set. Do not claim environment-
    independent regex semantics without verifying them.

No plugin registry, upstream AST subclassing, Redis cache, or new general JSONPath
parser is needed. One facade/query `Protocol` and two private adapters suffice.
During M1, engine-neutral metadata must preserve existing legacy behavior; the
target-language changes below belong to M2, not to introducing the abstraction.

### Required runtime semantic comparison

This belongs in `qontract_utils.jsonpath`, not in individual integrations or only
in the test suite. Successful compilation is not sufficient validation.

**Comparison contract:** compare the ordered sequence of complete matches,
including match count, typed concrete locations, duplicate occurrences, and
recursively type-aware values. Equal values at different locations are different
results. Python equality alone is insufficient because `True == 1 == 1.0`.
Compare mapping contents without treating object-key order as a value difference;
retain array order and the order of matches. Do not compare object identity
between independent copies; verify original-object identity on the returned
authoritative path separately.

**Isolation and mutation safety:** evaluate comparison queries on independent
in-memory copies of the same pre-operation input. Copy before either engine
evaluates it: `jsonpath-ng` 1.8.0 query evaluation itself can mutate dictionaries. Preserve
supported YAML subclasses and scalar types; do not use a JSON serialization round
trip as the copy mechanism. Never give the shadow engine the caller's mutable
document. Select the authoritative engine/result before updates or deletions.
Execute the chosen query on the original document once when needed to return
matches referencing that document, and apply the caller's mutation only once.
No second reconciliation, external API call, or duplicate mutation is permitted.

**Evaluate per input, not once per query:** the same expression can agree on an
array and disagree on an object or scalar. Do not cache a semantic pass/fail by
query text or skip later comparisons because an earlier input matched. Only
compilation outcomes and diagnostic emission may be cached/rate-limited. Calls
that only compile a query provide syntax coverage, not semantic coverage.

| Observation                                                                   | M1 result                                                                   | M2 result                                                                                                                                  |
| ----------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Both engines succeed and complete matches agree                               | `jsonpath-ng`                                                               | Python                                                                                                                                     |
| Python rejects syntax; `jsonpath-ng` succeeds                                 | `jsonpath-ng`; log `target_query_invalid`                                   | `jsonpath-ng`; log `legacy_fallback`                                                                                                       |
| Both succeed but values, types, paths, order, or duplicates differ            | `jsonpath-ng`; log `semantic_mismatch`                                      | `jsonpath-ng` for the unapproved difference; log `legacy_semantics_fallback`                                                               |
| Python has an eligible typed query-evaluation failure; `jsonpath-ng` succeeds | `jsonpath-ng`; log `target_evaluation_failed`                               | `jsonpath-ng`; log `legacy_fallback`                                                                                                       |
| Python succeeds; `jsonpath-ng` cannot parse a deliberate Python-only rewrite  | Preserve the actual `jsonpath-ng` failure; do not deploy this rewrite in M1 | Python; record that legacy comparison is not applicable, not that parity passed                                                            |
| Copying, comparison, or supported-input coverage is unavailable               | Preserve `jsonpath-ng` behavior; log `comparison_unavailable`               | Do not mark it compatible or apply unverified mutations; retain `jsonpath-ng` where safely evaluable, otherwise fail closed pending review |
| The authoritative query/both engines fail                                     | Preserve a real failure                                                     | Preserve a real failure                                                                                                                    |

Two empty match lists agree. An empty Python result and a nonempty `jsonpath-ng` result are
an observed mismatch; fallback is then based on comparison, not on emptiness
alone. Do not mix partial matches from different engines.

Expected behavior changes need a reviewed query rewrite or a narrow, explicitly
reviewed utility-owned migration decision with regression tests. Do not add a
reconcile-level engine/compatibility switch or automatically approve differences
because they were previously logged. Until reviewed, keep the legacy result.

Emit the exact safe query, source hint/fingerprint, engine names, mismatch kind,
and match counts. Do not log selected values, input documents, or secret-derived
literals. Bound comparison resources and measure copy/evaluation overhead. If a
comparison cannot safely complete within its supported limits, report unavailable
coverage rather than silently sampling, dropping the check, or claiming parity.
Tests must cover unsupported/cyclic data and comparison failures; do not add a
thread timeout that leaves background work running.

**Minimum regression examples:** string indexing, dictionary/scalar wildcards,
numeric-string and Boolean equality, quoted regex returning no matches in Python,
equal values at different locations, changed order, duplicate/root matches, and
the same query used consecutively on different input shapes. Mutation tests must
prove that copying/comparison never changes the original and updates happen once.

## 4. Query and behavior migration rules

**Timing:** this section is the M2 worklist. M1 logs incompatibilities without
rewriting queries or changing their execution semantics. Preserve the current
Jinja filter names throughout all three milestones.

### Syntax conversions

The inventory contains exact source/candidate pairs. Candidates use bracketed
names for reliable quoting; production changes should be minimal and readable.

| Existing form               | Target form                     | Required verification                                                               |
| --------------------------- | ------------------------------- | ----------------------------------------------------------------------------------- |
| `roles[*].'$ref'`           | `roles[*]['$ref']`              | Correct field selected, including context ownership.                                |
| `items.[0].name`            | `items[0].name`                 | Index/location unchanged. Generated concrete backrefs are handled separately below. |
| `[?name=="example"]`        | `[?@.name=="example"]`          | Relative-filter binding, especially GABI and patch paths.                           |
| `[?(@.a==1 & @.b==2)]`      | `[?(@.a==1 && @.b==2)]`         | Operator precedence and value types.                                                |
| `[?(@.name =~ "frontend")]` | `[?search(@.name, "frontend")]` | Search rather than full-match semantics, escapes, and missing/non-string fields.    |
| Quoted root name `'a/b'`    | `$['a/b']`                      | RFC 6901 pointer escaping.                                                          |

Do not use global string replacements: `&`, quotes, and dots may occur inside
regexes, literal values, Jinja expressions, or filenames. The offline AST-based
candidates in the inventory are planning evidence, not a permanent interpreter.

`{{ ctx_file_path }}` remains a Jinja substitution, rendered before compiling the
query. Keep the supported-variable restriction and cover quotes/backslashes in
context values. HCP generators must be changed along with their generated SaaS
configuration and expected-output fixtures.

### Intentional semantic differences require explicit tests

| Case                                          | Legacy `jsonpath-ng` result                     | Target direction                                                                               |
| --------------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Index a string with `[0]`                     | Selects first character                         | Target JSONPath does not index strings; use ordinary Jinja string indexing where intended.     |
| `[*]` applied to a dictionary                 | May wrap the whole dictionary as one array item | Target selects child values. Audit actual input types.                                         |
| `[*]` applied to a scalar                     | May return the scalar                           | Target returns no matches. Audit scalar-dependent expressions.                                 |
| Integer comparison against `"1"`, `1`, `True` | Can match all three                             | Target distinguishes string/number/Boolean. No global coercion shim.                           |
| Root JSON Pointer                             | Current helper constructs `/`                   | Target RFC pointer is empty string. Audit callers and document the deliberate contract change. |

Do not simply change test expectations until green. For each difference, record
the old behavior, the intended new behavior, and the affected consumer/config
change. Ordinary fixtures must retain equivalent output; only explicitly listed
language-contract differences may change.

### Mandatory special review: root-reset selector

`data/app-interface/changetype/gabi-owner.yml:19` contains `instances[*].$`
(inventory Q148). With zero instances it yields no matches; with two instances it
yields the root twice. Unconditionally replacing it with `$` is not equivalent
and can broaden change coverage for an empty list.

Before conversion, create old/new authorization fixtures for empty, one-item,
multi-item, added-file, removed-file, and changed-instance cases. Confirm the
intended grant with the change-type owner. Do not silently remove the selector,
broaden it to `$`, or treat a pseudo-root match as a real array location. This is
an explicit implementation gate, not a task for blind conversion.

### Mandatory special review: string-based secret-access validator

`resources/templates/change-type-secret-access-validation.j2` checks:

- `selector.startswith("allowedSecretParameterPaths")`;
- `"openshiftResources[*]" in selector`;
- `"?(" not in selector`.

Adding root prefixes or switching dotted names to brackets can bypass those
textual checks even if the query selects the same data. Preserve the current
spelling for compatible protected selectors. If changed syntax touches those
checks, update the validator in the same coordinated change and add negative
cases for rootless/rooted/bracketed spellings and positive provider-filtered
cases. Do not weaken or disable the validation to get the migration through.

## 5. M1: introduce the abstraction and observe, with jsonpath-ng authoritative

Each substep has a finish condition and should be a small independent PR/deployment.
Use characterization first and red/green regression tests for bugs. M1 contains
no app-interface query rewrite and no default-engine or language-contract change.

### M1.1 Freeze the evidence and establish baseline tests

- [ ] Record both checkout revisions and relevant existing modifications. Do not
      reset, stash, stage, or overwrite unrelated work.
- [ ] Refresh the inventory and resolve any newly discovered field/source kinds.
      Keep CLI JSONPath separate from the Python engine migration.
- [ ] Turn inventory source/candidate pairs into durable parameterized fixtures
      for implementation tests. Preserve source file/field context.
- [ ] Capture current authorization decisions, namespace sets, shard sets,
      pointers, mutation output, and rendered templates for representative data.
- [ ] Include raw scalar resources, nulls, empty lists/maps, repeated matches,
      mapping/list subclasses, falsy fields, and invalid expressions.
- [ ] Compare values with type awareness: Python equality alone would hide
      `True == 1` differences.
- [ ] Record root-reset and other semantic hazards for M2. Their existence must
      not block introducing a `jsonpath-ng`-backed facade or become an excuse to change
      authorization in M1.

**Finish:** reproducible baseline and complete exception list, not just passing
compile checks.

### M1.2 Build the package with both engines and jsonpath-ng as default

- [ ] Add the package and tests described in section 3.
- [ ] Add both pinned dependencies in the owning package; lock without unrelated
      upgrades. Preserve `jsonpath-ng` 1.8.0.
- [ ] Test against both real engines, with no live network dependency. Verify the
      utility-only engine parameter selects the intended adapter.
- [ ] Test escaping/locations, missing versus null, identity, mutations, root
      handling, error translation, threading, and multiprocessing serialization.
- [ ] Keep compilation bounded; cache successful and rejected target-validation
      outcomes so frequently used invalid queries are not repeatedly reparsed.
      Cache compiled queries, never document results.
- [ ] For every source query compiled through the facade, compile-check the exact
      rendered expression with Python as well. A typed syntax/type-validation
      rejection produces a migration diagnostic, but execution remains `jsonpath-ng`.
- [ ] Implement the runtime semantic comparison contract in section 3. Evaluate
      both query engines only on isolated copies during comparison; keep `jsonpath-ng` as
      the sole authoritative engine and never perform a second mutation path.
- [ ] Compare every actual evaluation input, even when compilation was cached.
      Log mismatches and unavailable comparisons without changing `jsonpath-ng` behavior.
- [ ] If `jsonpath-ng` rejects the query too, preserve the existing real failure. Validation
      must not turn invalid configuration into success or hide operational errors.
- [ ] Target over 80% coverage for new shared code and pass strict type/lint checks.

**Finish:** both adapters satisfy the same boundary, `jsonpath-ng` remains authoritative,
syntax rejection and silent mismatches are observable without changing `jsonpath-ng` results,
comparison is isolated, and no vendor types leak to consumers.

### M1.3 Make diagnostics searchable in CloudWatch and absent from Slack

The verified transport is **not a Python Slack handler**:

1. `reconcile/run_integration.py` writes both stdout and `LOG_FILE`.
2. The Fluentd sidecar tails `/fluentd/log/integration.log`.
3. `helm/qontract-reconcile/templates/template.yaml` copies that stream to
   CloudWatch and optional Slack/trigger notifications, with other error routes.

A global Fluentd grep exclusion or a Python file-handler exclusion would lose
the very CloudWatch evidence needed for M2. Implement selective routing instead.

- [ ] Emit a dedicated event/logger from the utility package, e.g.
      `event=jsonpath_migration`, `reason=target_query_invalid`, `phase=M1`,
      `primary_engine=jsonpath-ng`, `target_engine=python-jsonpath`, exact query,
      stable query fingerprint, exception type, and a single-line parse reason.
- [ ] Use the same CloudWatch-only event for `semantic_mismatch`,
      `target_evaluation_failed`, and `comparison_unavailable`. Include a typed
      difference category and match counts, never result payloads. Diagnostic
      rate limiting must not suppress actual comparisons on later inputs.
- [ ] Use the existing structlog/stdlib bridge so these fields survive into the
      actual text/file log, not just unused `LogRecord.extra` attributes. Encode
      embedded newlines so each diagnostic remains a single physical log line.
- [ ] Include source file/field hints where already available and retain existing
      integration/pod/stream context. Do not add an engine parameter to reconcile
      to obtain this context. Do not log documents, credentials, or selected data;
      for secret-derived query literals use a safe template hint/fingerprint.
- [ ] Rate-limit repeated identical diagnostics with a bounded process-local
      cache, for example once per query/reason/source per hour. Check emission on
      active use, not only on an LRU compilation miss: long-lived pods must keep
      producing discoverable evidence across the weeks/months observation window.
- [ ] Route only the explicit migration event to a CloudWatch-only Fluentd tag
      before the notification copy path. Reuse the chart's existing
      `rewrite_tag_filter` capability; keep ordinary records on their current path.
      Preserve migration events through any shared broad-drop filters as well.
- [ ] Verify normal Slack, trigger Slack, error-only Slack, and configured Gov
      Slack paths do not receive these diagnostics. Keep genuine integration
      warnings/errors and unrelated logs unchanged. Do not lower/suppress the
      entire package logger to avoid notifications.
- [ ] Test actual event rendering and routing for a diagnostic, a real error, an
      ordinary warning, and a lookalike message. Validate retention in CloudWatch,
      not just absence from a rendered Slack template.
- [ ] Change Helm source and regenerate chart-derived fixtures/manifests using
      the supported generators. Never hand-edit generated output.
- [ ] Deploy/verify this routing before broadly enabling compatibility diagnostics.

**Finish:** both a rejected query and a parse-valid query with differing results
produce CloudWatch evidence while `jsonpath-ng` behavior/status stays unchanged, and neither
sends a Slack message. Test the real routing, not just the chosen log level.

### M1.4 Move change-owner paths behind the boundary without changing decisions

- [ ] `reconcile/change_owners/diff.py`: replace `Diff.path` with `JsonLocation`.
      Build locations directly from DeepDiff's parsed field/index parts; remove
      `_DottedChild`, `_join_for_display`, and `_normalize_for_display`.
- [ ] Preserve readable log/report output with the project display formatter.
      Use typed locations, not display strings, for identity and coverage keys.
- [ ] `create_subdiff`: derive relative locations structurally, select old/new
      values without losing missing/null distinctions, and preserve current
      external diff semantics.
- [ ] `reconcile/change_owners/change_types.py`: `PathExpression` holds a
      `JsonQuery`; allowed changes are `JsonLocation` values from matches.
      Forward/backref and implicit ownership consume ordinary match values.
- [ ] Rewrite prefix, parent, and relative-path operations against locations.
- [ ] Replace `.filter(lambda x: True, data)` with concrete deletion on the
      copied coverage document. Preserve descending array-index removal and
      current empty-parent cleanup, split inheritance, disabled coverage,
      restrictive behavior, priorities, labels, and approver decisions.
- [ ] Do not make a previously uncovered root/list change self-serviceable as
      an incidental cleanup improvement.
- [ ] `reconcile/change_owners/changes.py`: adapt metadata-only locations and
      coverage keys; preserve current old/new handling and resource aggregation.
- [ ] Handle validator-generated concrete paths such as
      `array_field.[0].nested_ref` through a narrowly defined project concrete-
      path decoder, not by treating them as arbitrary target queries. Preserve
      the producer contract, reject ambiguous/unsupported encodings explicitly,
      and test real `/diff` fixtures before considering producer changes.
- [ ] `reconcile/change_owners/implicit_ownership.py`: use the query boundary.
- [ ] `reconcile/change_owners/tester.py`: replace full-path updates with explicit
      concrete-location updates and characterize root annotations.
- [ ] Migrate fixture patch helpers and all direct `jsonpath-ng`-based path assertions.

**Finish:** full `reconcile/test/change_owners/` suite passes; golden authorization,
coverage, priority, ownership, and legacy coercion behavior are unchanged. Keep
query syntax untouched. Ship this separately from the package/log-routing PRs.

### M1.5 Decouple shard selection without changing selected shards

The existing `apply_constraint_to_path` narrows selector wildcards using diff
locations. Production declarations currently use names and wildcards, not filters.

- [ ] Introduce an internal typed `ShardSelector` made of field/index/wildcard
      segments. Distinguish a wildcard from the literal object key `"*"`.
- [ ] Convert `DesiredStateShardConfig.shard_path_selectors` and declarations to
      this typed form. Do not introspect `python-jsonpath` selector classes or
      implement a general query-intersection algorithm.
- [ ] Implement the existing prefix-narrowing algorithm using those segments and
      `JsonLocation`; preserve its behavior when paths diverge or are shorter.
- [ ] Resolve the constrained shard path through project-owned traversal or the
      query boundary, preserving mapping wildcards and array indexes.
- [ ] Update declarations in `terraform_users.py`, `terraform_resources.py`,
      `terraform_tgw_attachments.py`, `terraform_vpc_resources/integration.py`,
      `openshift_resources_base.py`, `openshift_vault_secrets.py`,
      `openshift_rhcs_certs.py`, `openshift_managed_sso_client_secrets.py`,
      `prometheus_rules_tester/integration.py`, and
      `jira_permissions_validator.py`, plus test/demo declarations.
- [ ] Test additions, removals, whole-parent replacement, unrelated diffs,
      multiple indexes, dictionary wildcards, and old versus new shard values.
- [ ] Preserve configuration-based early exit, timeout fallback, and
      `sharded_run_review`; do not silently skip the check by returning no shards.

**Finish:** runtime/sharding suites retain affected-shard sets and timeout behavior,
and no shard logic imports either engine's AST.

### M1.6 Route remaining consumers through the default facade in small batches

| File                                                                       | Required change                                                                                                                                                                            |
| -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `reconcile/typed_queries/saas_files.py`                                    | Query through the boundary, retain matching-result cache and include/exclude identity, translate stable syntax errors to `ParameterError`.                                                 |
| `reconcile/saas_auto_promotions_manager/merge_request_manager/renderer.py` | Replace `_parse_expression` return typing and errors; preserve namespace inclusion/exclusion.                                                                                              |
| `reconcile/typed_queries/status_board.py`                                  | Replace parse/find calls; preserve excluded application names.                                                                                                                             |
| `reconcile/templating/lib/rendering.py`                                    | Replace patch/identifier lookups, preserve exactly-one-match validation, `$` scalar identifiers, literal `$ref` identifiers, and in-place updates.                                         |
| `reconcile/utils/mr/promote_qontract.py`                                   | Replace `match.context` and `match.path` access with concrete mutation; preserve both promotion methods' ruamel output.                                                                    |
| `reconcile/utils/jinja2/filters.py`                                        | Keep filter names; use `JsonQuery`/`JsonLocation`. Preserve result order, empty matches, input validation, and all `jsonpath-ng` semantics in M1. Target semantics are a tested M2 change. |
| `reconcile/utils/jsonpath.py`                                              | Remove old AST helpers after all consumers move; do not leave a permanent legacy compatibility module or barrel re-export.                                                                 |

- [ ] Include tests for mapping/list subclass identity and comment/quote retention.
- [ ] Verify `matches_jsonpath` checks match existence, not selected-value
      truthiness; zero, false, empty containers, and null can all be matches.
- [ ] Convert invalid-expression exception assertions to project exceptions while
      retaining useful caller-level error messages and original causes.
- [ ] Narrow dynamic match values to the consumer's expected mapping, sequence,
      scalar, or integration-owned typed model before use. Resolve type errors
      with real validation, not casts or suppression comments; retain references
      when a consumer mutates ruamel values.
- [ ] Audit every shared Jinja surface from section 2, not only the one literal
      filter occurrence found by grep. Test dynamic filter arguments too.

Migrate simple read-only selectors, then Jinja/template consumers, then mutations
as separate batches. Keep the existing root-pointer/filter behavior during M1;
do not apply the M2 semantic changes merely to make Python adapter tests pass.
It is acceptable to retain a narrow transitional helper until its last caller
is moved, but mark the remaining observation blind spots explicitly.

**Finish:** every production query path uses the package default, validation sees
rendered queries and actual evaluation inputs, syntax and semantic differences
are observed, and `jsonpath-ng` results/errors/mutations remain unchanged.
M1 is not complete while direct parser imports bypass observation. Begin the
weeks/months observation period after coverage and notification routing are verified.

## 6. M2: use observed queries to migrate, then make Python primary with jsonpath-ng fallback

### M2.1 Review weeks/months of evidence and plan small query batches

- [ ] Confirm CloudWatch retention covers the intended observation period in each
      environment. Retrieve logs using the cloudwatch-logs workflow; this plan
      does not authorize live log access or retention changes now.
- [ ] Search the migration event and group by integration, source, query, reason,
      and time. Deduplicate exact queries while retaining every affected caller.
- [ ] Search each observed query in app-interface and qontract-reconcile. Rendered
      `ctx_file_path`/HCP/GABI expressions may require locating their source
      template rather than searching only for the final literal expression.
- [ ] Reconcile those observations with the static inventory. Infrequent jobs,
      comparison-bundle checks, dormant configurations, tests, and generators may
      not have run during the observation window; zero logs is not proof of safety.
- [ ] Review `semantic_mismatch`, `target_evaluation_failed`, and
      `comparison_unavailable` as well as parser failures. Keep quoted regex,
      scalar/wildcard coercion, numeric/Boolean comparison, pointers, and root-reset
      ownership on the worklist even when no relevant input has been observed.
- [ ] Convert each confirmed case into a regression fixture with expected values,
      locations, authorization decisions, or rendered/mutated output.

### M2.2 Update controlled queries and generators in independently tested batches

- [ ] Use the inventory file-by-file index as the worklist. Fix rejected syntax
      and all quoted-regex cases; do not assume accepted expressions are safe.
- [ ] Keep compatible spellings where changing them would be unnecessary or
      affect string-based query validations.
- [ ] Convert ownership/context and implicit-ownership selectors, preserving
      `ctx_file_path` and old/new ownership resolution.
- [ ] Convert namespace include/exclude selectors and assert the exact selected
      `(cluster, namespace)` sets before and after migration.
- [ ] Update template patch paths and JSONPath identifiers; leave literal
      `$ref` identifiers alone.
- [ ] Change the GABI condition in
      `data/templating/templates/gabi/gabi-cluster-scope.yml` to use `@.` in its
      dynamically constructed filter. Test matching and nonmatching clusters.
- [ ] Update all five `hcp-collection/saas-*-target.yml` generators listed in
      the inventory, the generated service SaaS definitions, and the HCP template
      fixtures, including hive-shard variants.
- [ ] Resolve `gabi-owner.yml` and the secret-access validator gates above.
- [ ] Update change-type documentation examples to the chosen target dialect;
      retain motivation, ownership examples, and security warnings.
- [ ] Render templates before final compile testing; literal `{{ ... }}` parsing
      is not sufficient. Re-inventory the changed checkout and account for every
      source expression, including expected generated output.
- [ ] Before the default switch, merge only rewrites verified with **both** engines
      and equivalent behavior. Bracketed `$ref` fields or explicit `@.` may be
      suitable, but test each pair. Do not assume a syntax example is dual-compatible.
- [ ] Prepare Python-only rewrites such as `search()` and `&&` as follow-up batches;
      apply them after Python-with-fallback is running on every relevant consumer.
      Do not send new-only syntax to still-running M1 jobs with `jsonpath-ng` as primary.
- [ ] Do not edit a shared FedRAMP/commercial bundle assumption into the code.
      Inventory and validate each deployed app-interface instance separately.

**Finish:** early dual-compatible batches are safe on `jsonpath-ng`, Python-only batches are
prepared, and the remaining incompatibilities/fallback requirements are understood.
There is no requirement to complete every rewrite before M2 can start.

### M2.3 Switch the utility default, with a narrow and observable jsonpath-ng fallback

- [ ] Change only the utility's default engine to Python. Keep the same reconcile
      calls and both dependency pins. Exercise the default-change tests explicitly.
- [ ] If Python rejects a query at compile time with an eligible typed syntax or
      query-type error, compile/evaluate it with `jsonpath-ng` and log
      `reason=legacy_fallback`, the failing target error, and the exact query.
- [ ] Keep runtime semantic comparison enabled after the default switch. If both
      engines evaluate the actual input but disagree, use the legacy result for
      an unapproved difference and log `reason=legacy_semantics_fallback` before
      returning matches or applying updates. Do not rely only on known-syntax
      rules or target parse success; new mismatches must be caught too.
- [ ] A deliberate Python-only rewrite may not compile with `jsonpath-ng`. Execute it through
      Python after its regression tests and M2 rollout gate; distinguish this
      expected legacy syntax rejection from a successful parity comparison.
- [ ] Allow fallback for a documented typed query-evaluation incompatibility only
      when the read-only operation has not mutated anything. Fully materialize a
      result before returning it; never mix partial Python and legacy matches.
- [ ] Never retry an already-applied mutation with another engine. Match first,
      choose one result/engine, then perform project-owned mutations exactly once.
- [ ] Do not use empty matches alone, arbitrary exceptions, transport/authentication
      failures, resource exhaustion, or unexpected programming bugs as fallback
      signals. Two empty results agree; an empty/nonempty result difference is an
      actual semantic mismatch. Unknown comparison failures are coverage gaps,
      not evidence that the query is safe.
- [ ] If both engines reject/fail, retain a genuine failure with useful context;
      do not turn it into success or suppress its ordinary error notification.
- [ ] Log fallback diagnostics through the same CloudWatch-only route, with bounded
      repeat emission. Continue observing and migrating cases after the switch.
- [ ] Deploy and compare representative dry-runs before normal execution. Cover
      change owners, namespace selection, Jinja, promotions, and shard detection.

**Finish:** Python is the default everywhere, `jsonpath-ng` still protects known legacy
queries, fallback is discoverable without Slack noise, and no unexplained
authorization/selection/output differences remain in the tested scope.

### M2.4 Continue adapting queries and observe fallback decline

- [ ] Merge the prepared Python-only batches after all relevant consumers support
      M2. Update generators, expected outputs, code literals, and documentation too.
- [ ] Repeat CloudWatch review and turn new fallback reports into small tested fixes.
- [ ] Track unresolved static inventory entries separately from observed fallback.
- [ ] Resolve semantic gates such as `instances[*].$` explicitly; do not infer a
      safe rewrite from the absence of fallback reports.
- [ ] Require a representative clean observation window, including rare jobs and
      every environment, before proposing M3. Calendar time alone is insufficient.
- [ ] No unreviewed semantic mismatches or unexplained unavailable comparisons may
      remain. Record approved intended changes explicitly rather than treating
      fewer fallback logs as proof that behavior is identical.

## 7. M3: remove the fallback and jsonpath-ng dependency

- [ ] Confirm M2 exit evidence: no unresolved fallback cases, known semantic risks
      resolved, no unexplained unavailable comparisons, and static/dynamic query
      coverage accounted for. Explicitly review intended result differences.
- [ ] Remove the private `jsonpath-ng` adapter, fallback rules, legacy engine enum option,
      and `jsonpath-ng` dependency from the utility/root/lockfile wherever still present.
      Regenerate `uv.lock` without unrelated upgrades.
- [ ] Remove transition adapters and obsolete AST/rendering/hashability tests.
      Preserve their behavioral coverage using project-owned types.
- [ ] Verify `jsonpath-ng`/`jsonpath_ng` are absent from runtime code/dependencies,
      and Python vendor types occur only in the private Python adapter.
- [ ] Run the complete verification matrix below and check built package/runtime
      images, not just an isolated development environment.
- [ ] Update `AGENTS.md` and the relevant pattern documentation with the query /
      location boundary, mutation contract, filter semantics, and dependency owner.
- [ ] Keep the evaluation as history but mark the selected package and corrected
      exposure clearly; refresh this plan/inventory with final outcomes.

Keep stable diagnostic event definitions/routing until previous deployments are
retired and retained logs have served their purpose. Remove the `jsonpath-ng`-based runtime
comparator, temporary compatibility decisions, and unused observation-only
validation/throttling code; do not replace them with another shadow engine.
Retain the semantic regression corpus for future Python-library updates. Genuine
invalid-query errors must remain visible.

**Finish:** one runtime engine, no application AST coupling, no fallback dependency,
and complete rollout evidence. This is its own cleanup PR/release. Commit/PR
creation and external posting remain separately authorized.

## 8. Verification matrix

### Focused tests

| Suite / area                                            | What must be proved                                                                                                                                          |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| New `qontract_utils/tests/jsonpath/`                    | Stable API, both engines, utility-only engine selection, validation/fallback rules, identity, locations, errors, bounded caches, concurrency, and mutations. |
| `reconcile/test/change_owners/`                         | Same allowed/denied changes, split coverage, approvers, inheritance, restrictive types, priorities, labels, and backrefs.                                    |
| `reconcile/test/runtime/`                               | Same early exit and shard sets; multiprocessing transport and timeout behavior remain intact.                                                                |
| `reconcile/test/test_utils_jinja2.py`                   | Filter names and shape preserved; explicit target language differences; scalar strings are not decoded as JSON documents.                                    |
| `reconcile/test/templating/`                            | Patch cardinality/identity, scalar identifiers, rendered conditions, and in-place output.                                                                    |
| `reconcile/test/utils/test_mr.py`                       | Promotion updates preserve comments/quotes and unrelated fields.                                                                                             |
| SaaS typed-query, SAPM renderer, and status-board tests | Same selected namespaces, targets, and excluded applications.                                                                                                |
| Tests for all ten shard-declaring integrations          | Selector definition conversion did not change integration scope.                                                                                             |
| app-interface template/query validations                | All GABI/HCP fixtures render; string-based secret-access defenses remain effective.                                                                          |

Locate indirect test paths with the current checkout rather than assuming every
suite imports `jsonpath-ng` directly. Existing `make all-tests` covers many indirect callers.
Mock external APIs/Vault/network; tests should exercise the real JSONPath engine.
For reconciliation behavior, cover dry-run and apply using mocked mutations.

### Milestone-specific regression tests

- **M1:** rejected target syntax and parse-valid result differences both preserve
  exact `jsonpath-ng` output. Compare actual input copies on every evaluation, including
  cached queries and changing input shapes. Verify paths, ordering, duplicates,
  values, and recursively distinct primitive types. Shadow evaluation must not
  mutate the original, leak values, change exit status, or call external services.
  Test snapshot/unsupported-input failures and observable coverage gaps. Verify
  every diagnostic with real stdout/file formatting and Fluentd routing, including
  Slack trigger/error variants. Extend `reconcile/test/utils/test_helm.py` and test
  the rendered Fluentd configuration with shipped plugins, not YAML alone.
- **M2:** Python is the default; syntax rejection or unapproved result mismatch
  selects `jsonpath-ng` before authoritative execution/mutation. Both-empty results do not
  fall back; empty/nonempty disagreement does. Cover equal values at different
  paths, the four concrete behavior examples below, deliberate Python-only
  queries, both-engine failure, and unavailable comparison. Never mix partial
  results or replay mutations. Returned mutable values must reference the original
  document, even when comparison selected the fallback engine.
- **M3:** the installed runtime has no `jsonpath-ng` import/dependency; all supported queries
  run through Python and invalid queries fail without fallback. Retain every
  behavioral regression fixture created during M1/M2.

Mandatory real-engine fixtures (not mocked mismatches):

| Query and input                                                     | Legacy result      | Python result / required diagnostic                              |
| ------------------------------------------------------------------- | ------------------ | ---------------------------------------------------------------- |
| `$.name[0]` on `{"name":"api"}`                                     | `["a"]`            | `[]`; semantic mismatch                                          |
| `$.items[*]` on `{"items":{"name":"api"}}`                          | `[{"name":"api"}]` | `["api"]`; value/location mismatch                               |
| `$[?@.v==1].v` on `[{"v":"1"},{"v":1},{"v":true}]`                  | `["1",1,true]`     | `[1]`; match/type mismatch                                       |
| `items[?(@.name =~ "api")].name` on `{"items":[{"name":"my-api"}]}` | `["my-api"]`       | `[]`; semantic mismatch despite both parsers accepting the query |

Each fixture must prove M1 keeps the legacy result and M2 invokes the semantic
fallback, with a CloudWatch-only diagnostic. Also prove equal results produce no
mismatch event and different later input cannot reuse an earlier parity verdict.

### Required commands during implementation

```sh
make -C qontract_utils test
make all-tests
```

For app-interface YAML changes, follow its repository workflow:

```sh
make schemas
make bundle validate
```

Run these in the appropriate checkout. Inspect Make targets before execution:
`make all-tests` includes GraphQL/chart regeneration, and app-interface schema
refresh can require infrastructure access. Record blockers without suppressing
errors or discarding user changes. Run the existing affected template-test and
query-validation integrations in approved dry-run mode, not just schema validation.
For actual monitoring/template-rule changes, also run the repository's relevant
Prometheus tests. Documentation-only planning does not require these code checks.

### Representative dry-run and performance evidence

- Compare change-owner decisions for representative actual MR/bundle changes,
  including denied sensitive modifications and file creation/deletion.
- Compare namespace-selection sets for ACS, cert-manager, Dynatrace, and HCP
  collection patterns represented in the inventory.
- Render GABI, HCP generators, promotion mutations, resource templates, and the
  affected secret/template paths using mocked or approved read-only inputs.
- Compare a wildcard-mapping shard consumer and an array-path shard consumer.
- Measure total representative run times with warmed compilation caches. The
  goal is acceptable end-to-end latency, not a microbenchmark speedup.
- Add snapshot inputs/expected results to durable tests without leaking secrets
  or persisting complete production credential-bearing documents.

## 9. Incremental rollout, observation, and rollback

There is no planned big-bang image/bundle cutover or default requirement to pause
all integrations. M1 preserves `jsonpath-ng` execution; M2's fallback provides the migration
bridge. Changes still require normal deployment approval and dry-run verification.

### CloudWatch review workflow for M2

1. Verify M1 coverage, actual CloudWatch delivery, Slack exclusion, and retention.
2. Observe for the agreed weeks/months, covering normal, rare, and comparison-bundle
   executions. Keep the static inventory as a second worklist.
3. Query the diagnostic event across relevant integration log streams and dates.
   Search `target_query_invalid`, `semantic_mismatch`, `target_evaluation_failed`,
   and `comparison_unavailable`, then `legacy_fallback` and
   `legacy_semantics_fallback` after M2 deployment. Existing CloudWatch records
   contain a text `message`; do not assume diagnostic fields are top-level JSON.
4. Export a deduplicated query/source list, retaining first/last seen, integration,
   environment, and parser reason or mismatch kind. Do not save selected values
   or credential-bearing payloads. Account for unavailable comparisons separately.
5. Search source checkouts literally for each expression, then search template
   fragments where values were interpolated. Check both app-interface and
   qontract-reconcile, not just the first matching file.
6. Fix a small related batch, run its tests/dry-runs, deploy, and confirm those
   diagnostics disappear on subsequent active uses. Do not infer success solely
   because an hourly deduplication window has not elapsed.

The package owns policy; deployments do not gain an engine option. Changing the
default is a utility code/release change, tested via its library parameter.
Log-query execution and production operations are future authorized tasks.

### Release ordering

- M1: deploy log routing and the package with `jsonpath-ng` as default; then move callers in small
  behavior-preserving batches. Verify observation completeness before starting
  the long observation window.
- M2 preparation: apply dual-compatible rewrites; prepare target-only rewrites.
- M2 switch: deploy Python-default **with fallback** before any Python-only config
  reaches its consumers. Account for in-flight jobs, MR-check images, generators,
  comparison bundles, and each separately deployed app-interface instance.
- M2 follow-ups: migrate remaining fallback cases gradually and observe again.
- M3: only remove `jsonpath-ng` after both production observation and static/test coverage
  support removal. No old bundle that still needs fallback may be paired with M3.

### Rollback by milestone

- **M1:** roll back the affected package/caller batch; query configuration has not
  changed, so the existing `jsonpath-ng` image remains compatible. Log routing can remain.
- **M2 before target-only rewrites:** revert the utility default to `jsonpath-ng` in a utility
  release if tests confirm every deployed expression is still `jsonpath-ng`-compatible.
- **M2 after target-only rewrites:** do not blindly set `jsonpath-ng` primary or deploy an M1
  image. Prefer the last compatible M2 image with fallback, or restore the prior
  `jsonpath-ng`-compatible configuration together with a `jsonpath-ng`-primary image.
- **M3:** restore the last tested M2 image, which still includes fallback, while
  retaining the compatible configuration. Investigate the newly exposed query.
- For any milestone, stop and assess unexpected authorization/selection drift or
  already-applied external changes. Engine rollback does not undo mutations.

## 10. Milestone acceptance checklists

### M1: ready for the observation period

- [ ] Both pinned libraries are in the utility package; `jsonpath-ng` 1.8.0 is the default.
- [ ] Engine selection exists only as a utility parameter; reconcile has no knob.
- [ ] Every actual query path is routed through the facade and target-validated.
- [ ] Invalid target syntax logs an actionable diagnostic without changing `jsonpath-ng` behavior.
- [ ] Parse-valid result differences are compared per input and logged; `jsonpath-ng` remains
      authoritative for values, paths, ordering, duplicates, and mutations.
- [ ] Shadow comparison is isolated; original identities and exactly-once mutation
      behavior are preserved. Unavailable comparisons are visible coverage gaps.
- [ ] Diagnostics survive into CloudWatch and are excluded from all Slack routes.
- [ ] Repeated active use remains observable without unbounded logging/caching.
- [ ] Authorization, shards, outputs, mutation behavior, and exit status are unchanged.
- [ ] Focused/full tests and representative dry-runs pass for each caller batch.

### M2: Python primary, remaining work visible

- [ ] Weeks/months of CloudWatch evidence have been reviewed against the inventory.
- [ ] Query fixes are small tested batches; generators and fixtures are included.
- [ ] Python is the utility default, with `jsonpath-ng` retained as a logged fallback.
- [ ] Runtime result comparison catches new as well as known semantic mismatches;
      unapproved differences use `jsonpath-ng` before mutations and remain observable.
- [ ] No fallback is based on empty results alone, broad exceptions, or replayed mutations.
- [ ] Intentional result changes and Python-only rewrites have explicit regression
      coverage; unavailable comparison is never counted as a parity pass.
- [ ] Both-engine failure still fails normally and is not hidden from notifications.
- [ ] Target-only syntax reaches consumers only after their M2 support is deployed.
- [ ] Rare jobs, environments, and comparison-bundle paths are included in the
      clean fallback observation window; unresolved static cases remain tracked.

### M3: final acceptance

- [ ] User-selected `python-jsonpath` is the sole runtime JSONPath engine.
- [ ] Dependency is owned by `qontract_utils`, with no optional strict extras.
- [ ] Only the private Python adapter imports vendor query/match/selector/exception types.
- [ ] Concrete paths, display, coverage, pointers, and sharding are engine-independent.
- [ ] No general legacy interpreter or permanent dual-engine production mode.
- [ ] Every inventory occurrence is migrated, retained with verified behavior, or
      explicitly classified out of scope; dynamic/template cases are rendered.
- [ ] Every target behavior change has a documented consumer-level test.
- [ ] Root-reset ownership semantics and secret-access validator defenses are resolved.
- [ ] Existing Jinja filter names remain; controlled rendering surfaces are audited.
- [ ] Authorization, namespace sets, shard sets, and mutations have no unexplained drift.
- [ ] Full checks and approved representative dry-runs pass; limitations are recorded.
- [ ] Milestone-specific release ordering and rollback compatibility are documented.
- [ ] Unrelated work, generated files, package boundaries, and early-exit policy are preserved.

## References

- <https://pypi.org/project/python-jsonpath/2.2.2/>
- <https://github.com/jg-rp/python-jsonpath/blob/v2.2.2/CHANGELOG.md>
- <https://jg-rp.github.io/python-jsonpath/api/>
- <https://jg-rp.github.io/python-jsonpath/syntax/>
- <https://github.com/jg-rp/python-jsonpath/blob/v2.2.2/jsonpath/path.py>
- <https://github.com/jg-rp/python-jsonpath/blob/v2.2.2/jsonpath/env.py>
- [ADR-007: shared utilities](../adr/ADR-007-no-reconcile-changes-migrate-utils.md).
- [ADR-012: typed models](../adr/ADR-012-typed-models-over-dicts.md).
