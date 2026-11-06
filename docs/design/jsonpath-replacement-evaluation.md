# JSONPath replacement evaluation

Date: 2026-11-05

Ticket: <https://redhat.atlassian.net/browse/APPSRE-15715>

Status: Research and proposed migration path; implementation not approved.

**Decision update:** The user selected `python-jsonpath`, accepting the measured
millisecond-scale overhead in exchange for its dependency-free API. The proposed
approach in [jsonpath-migration-proposal.md](jsonpath-migration-proposal.md) and
the [complete app-interface inventory](app-interface-jsonpath-inventory.md)
supersede the initial recommendation below. A standalone, more detailed
milestone plan is still in progress and not yet published. Subsequent
code-path tracing also narrowed the tenant-exposure concern: ordinary tenant
SaaS templates do not receive our Jinja filters. Audit the shared
app-interface rendering surfaces rather than assuming an unknown external
Jinja ecosystem requires indefinite legacy filters. The remaining sections
preserve the original research history. The current rollout is explicitly
**M1: `jsonpath-ng` default plus Python syntax and result-comparison
diagnostics (CloudWatch only), M2: Python default with `jsonpath-ng` fallback
after an observation period, M3: resolve the engine decision** (see
`jsonpath-migration-proposal.md`). The milestone plan supersedes the original
paired-cutover/deprecation sequence.

## Summary

The recommended target engine is **`jsonpath-rfc9535==2.0.2`**. It has verified
2026 repository activity, a small typed API, concrete match locations, and good
measured performance. `python-jsonpath==2.2.2` is the strongest alternative if
having no mandatory dependencies takes priority over cached evaluation speed.

**None of the evaluated candidates is a verified drop-in replacement for the
existing JSONPath contract.** The migration affects configuration syntax,
change-owner authorization, shard selection, mutations, and public Jinja filters.
Unknown tenant-repository templates prevent a complete static compatibility audit.

The sustainable approach is to use standardized query semantics and project-owned
concrete paths, migrate controlled consumers, explicitly version the Jinja
contract, and remove `jsonpath-ng` after retiring legacy consumers.

## Motivation and requirements

The ticket records repeated breakage while attempting to upgrade `jsonpath-ng`
from 1.8.0 through 1.15.0 and 1.16.0. Changes included scalar indexing, wildcard
coercion, new type information, path rendering, and a new `Wildcard` AST node.
Compatibility subclasses broke again when the underlying AST changed.

The current checkout pins `jsonpath-ng==1.8.0`. The preserved upgrade work is on
the fork branch `2026-11-04_jsonpath-ng-1.15-upgrade-wip`.

The requested replacement should:

- Have at least one verified commit in 2026.
- Have a reasonably stable API, assessed through its changelog.
- Fit qontract-reconcile's querying, location, and mutation needs.
- Have an easy-to-use API.
- Preferably have no other runtime dependencies.
- Be fast, including when expressions are already compiled.

## Scope and evidence

The investigation used:

- The Jira description and the local qontract-reconcile checkout, whose recorded
  HEAD was `25e55d69` on 2026-11-05.
- PyPI release metadata, dependency metadata, and distribution files.
- Actual upstream commit records, rather than repository update timestamps or
  package upload dates as substitutes for activity.
- Available changelogs, release notes, documentation, and selected source code.
- The local app-interface checkout at
  `/Users/cassing/workspace/gitlab-cee/cassing/app-interface`.
- Selected qontract-validator and qontract-schemas sources to identify externally
  generated paths and configuration fields.
- Isolated compatibility probes and microbenchmarks using exact package versions.

The current root `pyproject.toml` requires Python `==3.14.*`, despite the older
Python 3.12 requirement described in `AGENTS.md`. Initial probes ran on Python
3.12; the final comparison also ran on Python 3.14.

These findings describe the inspected local configuration snapshot. They do not
establish complete tenant usage or production behavior. No full integration
migration, full project test suite, or production dry-run was performed.

## Candidate comparison

Versions and activity were checked on 2026-11-05. Runtime dependencies below
exclude optional development dependencies.

| Package              | Version | Verified 2026 activity    | Runtime dependencies                          | Assessment                                                                                                                                                         |
| -------------------- | ------- | ------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `jsonpath-rfc9535`   | 2.0.2   | Oct 10                    | `regex`, `iregexp-check`                      | Recommended target: standardized syntax, typed locations, and fast evaluation.                                                                                     |
| `python-jsonpath`    | 2.2.2   | Oct 29                    | None; strict extras are optional              | Best dependency-free alternative; good high-level API and documentation, but slower cached evaluation in the probes.                                               |
| `jsonpath-python`    | 1.1.6   | May 7                     | None                                          | Fast and simple, but incompatible/error-prone behavior in probes; weaker fit for authorization-sensitive consumers.                                                |
| `jsonpath-mojo` | 0.2.6 | Oct 31, repository-level | None declared | Young project; advertised compatibility targets `jsonpath-ng` 1.7.0 and explicitly excludes required regex extensions and some nested filters. |
| `jsonpath-nz`        | 1.0.6   | None found                | None declared                                 | Latest commit found across published branches was June 2025; fails the activity requirement.                                                                       |
| `jsonpath-sleuth`    | 0.1.11  | Apr 17                    | None declared; Rust extension                 | Young project; documented query interface returns values, without the matching location/mutation API needed here. No published changelog or GitHub releases found. |
| `fetch-jsonpath-mcp` | 1.2.0   | Sep 27                    | Includes `jsonpath-ng`, HTTP and MCP packages | An MCP application, not a replacement engine; retains the dependency.                                                                                              |
| `pulse-jsonpath-ng`  | 0.1.0   | Jun 18                    | `jsonpath-ng`                                 | Parser accelerator, not a replacement; only one initial commit found.                                                                                              |
| `dg-jsonpath-ng` | 1.8.0 | Apr 6 | None declared | A `jsonpath-ng` fork whose latest work synchronizes upstream; little evidence that it resolves the maintenance problem. |
| `simple_jsonpath`    | 0.4.4   | Mar 24                    | `orjson`, `typing-extensions`                 | Young read-only implementation; documented breaking public API changes and two yanked recent releases.                                                             |
| `aero-jmespath`      | 0.4.0   | Oct 3, successor monorepo | None declared                                 | Inconsistent package/documentation naming; latest PyPI release supplies only a Windows wheel, unsuitable for production Linux.                                     |

Repository-level activity in a multi-package repository is weaker evidence than a
history of substantive maintenance on the particular package.

### Additional packages

- **`jmespath` 1.1.0:** verified commit on 2026-01-22, no runtime dependencies,
  and already present transitively. It introduces a different query language and
  lacks the required location-oriented interface, so it is not a suitable direct
  replacement.
- **`jsonpath2` 0.4.5:** latest default-branch commit found was in December 2022;
  depends on `antlr4-python3-runtime==4.10`.
- **`jsonpath-rw` 1.4.0:** has a real 2026-10-30 fix, but its latest published
  PyPI release remains from 2015. A recent commit alone does not establish a
  healthy release process.
- **`jsonpath-rw-ext` 1.2.2:** latest default-branch commit and release found were
  from July 2019.
- **`jsonpath-rust`:** a Rust crate exists, but there was no PyPI distribution
  under that exact name during the investigation.

## API stability and maintenance findings

### jsonpath-rfc9535

- The repository dates from March 2024; version 1.0 declared stable status in
  November 2025.
- Version 2.0 explicitly documented breaking Python API changes, including
  `JSONPathNode.parent` changing from a property to a method, removed methods,
  and environment configuration changes.
- The 2.0 changelog states that JSONPath syntax and semantics were unchanged.
- Version 2.0.1 corrected comparison and parsing behavior, including Boolean
  comparisons and rejecting hyphens in unquoted shorthand names.
- Version 2.0.2 restored traversal of `dict` and `list` subclasses. This matters
  for ruamel YAML data and is one reason to start at this exact version.
- The package ships `py.typed` and supports Python 3.12 through 3.14.
- The high-level interface offers `compile`, `find`, `findall`, node values,
  and concrete `location` tuples. Assigning a non-root node's value updates its
  source object; this was verified with a ruamel document.
- Its data model is narrower than arbitrary Python `Mapping`/`Sequence` objects.
  A `UserDict` probe returned no match where `jsonpath-ng` returned a value. Audit actual
  input types; ruamel subclasses worked in the tested version.

The release history is encouraging, but it does not guarantee unchanged behavior
forever. Keep application logic independent of private parser and AST classes.

### python-jsonpath

- The repository dates from March 2023 and has substantive October 2026 commits.
- Version 2.0 explicitly documented syntax changes and an internal AST redesign.
  It also introduced strict mode.
- Earlier minor releases changed normalized paths, serialization, filter
  precedence, and existence/comparison behavior.
- Recent 2.x releases primarily added patch operations and corrected parsing,
  recursion errors, and JSON Patch semantics.
- Its high-level API includes compiled queries, match values, `parts`, parents,
  JSON Pointers, and JSON Patch. It ships `py.typed`.
- It has no mandatory dependencies. The `strict` extra adds `regex` and
  `iregexp-check`; installed optional regex packages can affect regex handling.

This is a good library, but adopting its AST throughout the application would
recreate the current coupling problem.

### Other changelog findings

- `jsonpath-python` 1.1.5 fixed code execution through filter `eval`; 1.1.6 fixed
  regex filter injection. These are historical fixes, not claims that the tested
  current release remains vulnerable. Probes of 1.1.6 nevertheless showed
  malformed expressions returning empty results and a Boolean filter silently
  failing to match.
- `simple_jsonpath` 0.2.1 release notes explicitly state breaking public API
  changes. PyPI releases 0.4.2 and 0.4.3 are yanked.
- `jsonpath-mojo` has a short, shared monorepo changelog and a project history
  starting in September 2026. Its benchmarks include parsing on each `jsonpath-ng` call,
  which differs from qontract-reconcile's cached helper.

## app-interface usage audit

The expanded structured-field audit found **987 occurrences, 381 distinct
expressions, and 232 files**. Counts include configuration and template-test
fixtures. Expressions can appear in multiple categories, so distinct counts per
category must not be added together.

| Usage                                     | Occurrences | Files | Distinct expressions | python-jsonpath parse failures | RFC parse failures after adding root prefix |
| ----------------------------------------- | ----------- | ----- | -------------------- | ------------------------------ | ------------------------------------------- |
| Change-type selectors                     | 453         | 133   | 289                  | 13                             | 25                                          |
| Ownership-context selectors               | 78          | 28    | 33                   | 21                             | 21                                          |
| Implicit-ownership selectors              | 5           | 5     | 5                    | 4                              | 4                                           |
| Namespace selectors                       | 371         | 27    | 22                   | 22                             | 22                                          |
| Status-board selectors                    | 2           | 2     | 1                    | 0                              | 0                                           |
| Template patch paths/JSONPath identifiers | 78          | 66    | 36                   | 18                             | 18                                          |

The earlier, narrower scan covered 340 distinct expressions across 164 files:
55 failed parsing with `python-jsonpath`, and 67 failed with the RFC engine after
root-prefix normalization. The expanded audit additionally covered singular
implicit-ownership selectors, global status-board selectors, and template patch
paths/identifiers.

**Parsing success does not mean semantic equivalence.** The earlier scan found
12 quoted-regex expressions that compiled with `python-jsonpath`; a representative
probe showed that the old quoted `=~` form silently returned different results.

### Syntax currently in use

| Legacy form                 | Standardized target form        |
| --------------------------- | ------------------------------- |
| `roles[*].'$ref'`           | `$.roles[*]['$ref']`            |
| `items.[0].name`            | `$.items[0].name`               |
| `[?name=="example"]`        | `[?@.name=="example"]`          |
| `[?(@.a==1 & @.b==2)]`      | `[?(@.a==1 && @.b==2)]`         |
| `[?(@.name =~ "frontend")]` | `[?search(@.name, "frontend")]` |

Representative translations were verified against the current engine and the
finalists. This does not prove a generic translator correct. Translation must
respect quoting, escaping, nested expressions, regex dialects, and templates.

Other cases to preserve or explicitly migrate include:

- Rootless queries and quoted top-level names.
- Hyphenated field names, which need bracket quoting under strict RFC syntax.
- Bare comparison literals, which `jsonpath-ng` accepts in some expressions.
- A configured `instances[*].$` expression, whose root-reset behavior needs an
  explicit conversion rather than a mechanical punctuation replacement.
- Context selectors interpolating `{{ ctx_file_path }}`.
- Status-board exclusion `apps[?@.onboardingStatus!="OnBoarded"]`.
- Template patch identifiers equal to `$`, which select scalar list elements.
  Identifiers equal to `$ref` are handled as ordinary field names by the existing
  renderer and must not be mistaken for JSONPath queries.

### Generated expressions

Five templates under `data/templating/templates/hcp-collection/` generate namespace
selectors containing legacy regex and conjunction syntax:

- `saas-logs-forwarder-target.yml`
- `saas-metrics-target.yml`
- `saas-rmo-config-target.yml`
- `saas-logs-event-collector-target.yml`
- `saas-logs-token-refresher-target.yml`

For example, `saas-metrics-target.yml` generates a selector from
`static.hive_cluster_pattern` and `static.environment`. Updating generated SaaS
files alone would leave the generator producing the old dialect.

### Dynamic Jinja usage and unknown tenant consumers

The shared Jinja environment registers these public filters in
`reconcile/utils/jinja2/utils.py`:

- `extract_jsonpath`
- `matches_jsonpath`
- `json_pointers`

A concrete local use exists in
`data/templating/templates/gabi/gabi-cluster-scope.yml:11`. It dynamically builds:

```text
$.gabi_instances[*].instances[?namespace.cluster.name=="..."]
```

That expression works with `jsonpath-ng` 1.8.0 and fails with both finalists because the
filter's relative field reference lacks `@.`.

The shared renderer is also used by resource templates and other integrations.
Templates may come from tenant repositories or external lookups, and expressions
can be assembled at runtime. **The local audit cannot enumerate that complete
public contract.** Lack of a local match is not evidence that a feature is unused.

## Verified semantic differences

The following probes used `jsonpath-ng` 1.8.0 and the exact finalist versions above:

| Expression and input | `jsonpath-ng` 1.8.0 | Both finalists |
| ---------------------------------------- | ---------------------- | ------------------- |
| `[0]` against `"abc"`                    | `["a"]`                | `[]`                |
| `a[0]`, with `a="abc"`                   | `["a"]`                | `[]`                |
| `a[*]`, with `a={"x":1,"y":2}`           | `[{"x":1,"y":2}]`      | `[1,2]`             |
| `a[*]`, with `a=7`                       | `[7]`                  | `[]`                |
| Filter `v==1` over `"1"`, `1`, `True`    | Matches all three      | Matches numeric `1` |
| Filter `v==true` over `"1"`, `1`, `True` | Matches `1` and `True` | Matches `True`      |

The RFC queries in these probes used the required root prefix. Null input and
existence tests over falsy-but-present values behaved consistently in the tested
cases. The RFC engine also preserved a top-level non-JSON string selected with `$`.

These differences can affect namespace selection, authorization, and rendered
resources without raising an exception. Falling back to the old engine only on
parse errors would not detect them.

Other verified details:

- `python-jsonpath` match pointers correctly escaped `/` as `~1` and `~` as `~0`.
  Its root pointer is the RFC-defined empty string; the current helper constructs
  `/` for an empty path, so root-pointer behavior needs a deliberate contract test.
- Both finalists located values in the tested ruamel object. Updating the value
  preserved the tested comment and quote information.
- Generic mapping compatibility differs: `jsonpath-rfc9535` did not traverse a
  `UserDict` in the probe. Its documented input domain is JSON-like dictionaries
  and lists, including their supported subclasses.

## Performance measurements

The final comparison ran on CPython 3.14.5, macOS ARM64. The document contained
1,000 records shaped as follows, with `enabled` alternating by index:

```json
{
  "items": [
    {"name": "ns-0", "enabled": true, "nested": {"name": "nested-0"}},
    {"name": "ns-1", "enabled": false, "nested": {"name": "nested-1"}}
  ]
}
```

Expressions were compiled before evaluation. Each evaluation materialized match
values from location-bearing results, and output equality was asserted before
timing. Measurements used `timeit.repeat`, 30 operations per batch, five batches,
and the median time per operation. These are local microbenchmarks, not measured
integration or production speedups.

Milliseconds per cached evaluation; lower is better:

| Query | `jsonpath-ng` 1.8.0 | python-jsonpath 2.2.2 | RFC 2.0.2 |
| ---------------------------------- | -------- | --------------------- | --------- |
| `$.items[*].name`                  | 0.851    | 1.794                 | 0.343     |
| `$.items[?(@.enabled==true)].name` | 1.655    | 4.121                 | 1.355     |
| `$..name`                          | 4.864    | 9.743                 | 1.252     |

The RFC engine was about **1.2-3.9 times faster** for these cached workloads.
`python-jsonpath` was about **2-2.5 times slower**. Initial Python 3.12 measurements
showed the same overall direction.

Compilation was much faster in both finalists:

| Query | `jsonpath-ng` compilation, microseconds | python-jsonpath compilation, microseconds | RFC compilation, microseconds |
| ---------------------------------- | ---------------------------- | ----------------------------------------- | ----------------------------- |
| `$.items[*].name`                  | 1,860                        | 9.82                                      | 3.29                          |
| `$.items[?(@.enabled==true)].name` | 6,285                        | 30.78                                     | 7.09                          |
| `$..name`                          | 1,783                        | 5.73                                      | 1.48                          |

`reconcile/utils/jsonpath.py` already uses an LRU compilation cache with capacity
256, although some callers bypass it. Parser-only speedup claims therefore do
not describe the existing hot path. Keep compilation and evaluation measurements
separate and benchmark representative integration workloads before rollout.

`jsonpath-python` was also benchmarked separately because it shares the import
namespace `jsonpath` with `python-jsonpath`. Some matching workloads were faster
than `jsonpath-ng`, but the Boolean-filter workload produced different results and was not
treated as a valid speed comparison.

## Dependency and packaging tradeoff

`jsonpath-rfc9535` requires `regex` and `iregexp-check`:

- `regex` already exists in this workspace's dependency graph.
- `iregexp-check` would be one net-new transitive package. Version 0.1.4 declares
  no further runtime dependencies and publishes ABI3 wheels for common Linux,
  macOS, and Windows architectures.
- These dependencies include native components, so the target engine is not an
  entirely pure-Python dependency closure.

`python-jsonpath` has no mandatory dependencies and is the better option if that
preference outweighs the measured evaluation difference. Neither finalist
preserves `jsonpath-ng`'s legacy dialect automatically.

The current `jsonpath-ng` 1.8.0 metadata also declares no external runtime dependencies.
Replacing it should not be described as automatically removing a separate `ply`
dependency from this lockfile.

## Required code changes

The inspection found 13 source files directly importing `jsonpath-ng` or the existing
JSONPath helper, plus 12 directly referencing test/fixture files. Indirectly
affected consumers and tests extend beyond those counts.

| Area                     | Files                                                                                                               | Required work                                                                                                                                                 |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shared query/path helper | `reconcile/utils/jsonpath.py`                                                                                       | Cached query boundary, stable error handling, and project-owned concrete locations.                                                                           |
| Change ownership         | `reconcile/change_owners/change_types.py`, `changes.py`, `diff.py`, `implicit_ownership.py`, `tester.py`            | Replace AST-based locations, prefix checks, splitting, deletion, annotation updates, and `_DottedChild` rendering. Preserve ownership and coverage decisions. |
| Shard selection          | `reconcile/utils/runtime/desired_state_diff.py`                                                                     | Replace wildcard narrowing without relying on upstream AST internals.                                                                                         |
| Jinja filters            | `reconcile/utils/jinja2/filters.py`                                                                                 | Preserve or explicitly version query semantics, errors, ordering, scalar behavior, and JSON Pointer behavior.                                                 |
| Template patching        | `reconcile/templating/lib/rendering.py`                                                                             | Preserve matched-object references, patch cardinality, and identifier behavior.                                                                               |
| Promotion mutations      | `reconcile/utils/mr/promote_qontract.py`                                                                            | Replace `match.context`/`match.path` access while preserving ruamel data.                                                                                     |
| Namespace selectors      | `reconcile/typed_queries/saas_files.py`, `reconcile/saas_auto_promotions_manager/merge_request_manager/renderer.py` | Replace query calls, preserve include/exclude results, and update error translation.                                                                          |
| Status board             | `reconcile/typed_queries/status_board.py`                                                                           | Replace selection calls and preserve excluded applications.                                                                                                   |

Manifest/lockfile changes would affect `pyproject.toml` and `uv.lock`, with the
dependency declaration placed according to the final helper's package location.

### Separate query expressions from concrete locations

An expression such as `$.resourceTemplates[*].targets[*].ref` is a query. A match
location is concrete and can be represented independently of the query engine:

```text
("resourceTemplates", 0, "targets", 2, "ref")
```

Project-owned field/index tuples can support equality, ancestry, lookup,
deletion ordering, display, serialization, and JSON Pointer conversion. Preserve
the distinction between an integer index and a numeric-looking object key.

This removes the need for `Child`, `Fields`, `Index`, `Slice`, and display
subclasses in change-owner business logic. Root changes, missing values, list
reordering, descending-index deletion, and empty-parent cleanup need explicit
behavioral coverage.

All inspected production shard selectors use field names and wildcards, such as
`state.*.shard`, `accounts[*].name`, and
`roles[*].aws_groups[*].account.name`. A limited project-owned representation can
cover that existing subset; it should not become another general JSONPath parser.
Any declaration/API changes also require updating the integration callers.

qontract-validator generates concrete backref paths such as
`array_field.[0].nested_ref`. These enter change-owner processing through
`FileRef.json_path` and must be included in the migration corpus, even though
they are not handwritten app-interface selector fields.

## Proposed migration sequence

### 1. Characterize behavior and introduce the application boundary

Keep `jsonpath-ng` 1.8.0 authoritative while adding meaningful characterization coverage.
Decouple concrete paths, display, and ownership calculations from the `jsonpath-ng` AST
before switching engines. Preserve current behavior during this step.

The comparison corpus should cover:

- app-interface selectors with representative actual input documents;
- generated templates and their rendered selectors;
- current change-owner, shard-selection, promotion, and patch-rendering tests;
- validator-generated backref paths;
- scalar, wildcard, comparison, escaping, root, and missing-value cases from the
  ticket and this investigation;
- invalid-expression errors, ordering, duplicate matches, and object identity.

### 2. Migrate controlled consumers with differential validation

Introduce the new engine through explicit selection during the transition.
Compare values, concrete locations, errors, authorization decisions, affected
shards, and rendered output against the old implementation.

Migrate the controlled app-interface dialect, including template generators and
test fixtures. Coordinate configuration and backend rollout: new syntax such as
`&&` is not accepted by the old parser. The exact deployment bridge remains an
implementation-design decision; automatic parse-error fallback is insufficient.

Do not claim a generic legacy translator preserves semantics merely because it
rewrites quotes and operators. If a transition translator is used, constrain it
to verified syntax and test it independently.

### 3. Version and retire the public Jinja contract

The preferred transition is new, explicitly RFC-defined filter variants while
the existing filter names retain their current behavior during migration.

1. Migrate first-party templates to the new contract.
2. Observe actual tenant usage and optionally shadow-compare results while the
   legacy result remains authoritative.
3. Publish semantic differences and a deprecation window.
4. Migrate consumers and retire legacy filters under that explicit policy.
5. Remove `jsonpath-ng` and transition machinery.

Runtime observations improve coverage but do not prove that dormant or future
tenant templates have been exercised. If the existing filter names must retain
full compatibility indefinitely, removing `jsonpath-ng` requires a substantial legacy
compatibility implementation. None of the investigated libraries eliminates
that work, and owning another legacy interpreter would undermine toil reduction.

### 4. Validate and remove the dependency

Run focused compatibility tests, the required full `make all-tests`, and relevant
package checks. Run representative dry-runs for change ownership, namespace
selection, templating, and sharded checks before rollout.

Only after legacy consumers are retired should the `jsonpath-ng` dependency be deleted from
the manifests and lockfile. Final acceptance must include authorization and
selection parity, rather than only matching ordinary query values.

## Risk assessment and open decisions

| Change                                                | Assessment                                                                                        |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Immediate global engine replacement                   | High risk: silent changes can affect authorization, deployment selection, and rendered resources. |
| Controlled internal migration with differential tests | Medium risk; concrete-path isolation and existing tests make it tractable.                        |
| Existing tenant Jinja filters                         | High/unknown risk until the compatibility or deprecation contract is settled.                     |
| Future dependency upgrades after AST decoupling       | Reduced coupling, but changelog review and behavioral tests remain necessary.                     |

Open decisions before implementation:

- Approve the RFC engine's dependency tradeoff versus the dependency-free
  `python-jsonpath` alternative.
- Define the legacy Jinja compatibility/deprecation policy.
- Choose a coordinated configuration/backend rollout mechanism.
- Validate actual JSON-like input types and representative end-to-end performance.

This is a multi-step migration rather than a routine version bump. No precise
implementation-duration estimate was established during this research.

## Sources

### Recommended engine and alternative

- <https://pypi.org/project/jsonpath-rfc9535/>
- <https://github.com/jg-rp/python-jsonpath-rfc9535>
- <https://github.com/jg-rp/python-jsonpath-rfc9535/blob/main/CHANGELOG.md>
- <https://github.com/jg-rp/python-jsonpath-rfc9535/commit/abef31f69e9b3de7bbaa0d37209b5df787d3d88b>
- <https://github.com/jg-rp/python-jsonpath-rfc9535/blob/main/src/jsonpath_rfc9535/_node.py>
- <https://pypi.org/project/python-jsonpath/>
- <https://github.com/jg-rp/python-jsonpath/blob/main/CHANGELOG.md>
- <https://github.com/jg-rp/python-jsonpath/commit/bd91a15094796927cd683c628169c1a8e8b6ddb6>
- <https://jg-rp.github.io/python-jsonpath/api/>
- <https://pypi.org/project/iregexp-check/>
- <https://pypi.org/project/regex/>

### Other evaluated candidates

- <https://pypi.org/project/jsonpath-python/>
- <https://github.com/sean2077/jsonpath-python/blob/main/CHANGELOG.md>
- <https://pypi.org/project/jsonpath-mojo/>
- <https://github.com/thyn-ai/mojo-kernels/blob/main/CHANGELOG.md>
- <https://pypi.org/project/jsonpath-nz/>
- <https://github.com/arusatech/jsonpath-nz>
- <https://pypi.org/project/jsonpath-sleuth/>
- <https://github.com/EricDalrymple91/jsonpath-sleuth>
- <https://pypi.org/project/fetch-jsonpath-mcp/>
- <https://github.com/ackness/fetch-jsonpath-mcp>
- <https://pypi.org/project/pulse-jsonpath-ng/>
- <https://github.com/AstekGroup/pulse-jsonpath-ng>
- <https://pypi.org/project/dg-jsonpath-ng/>
- <https://github.com/denisfrm/jsonpath-ng>
- <https://pypi.org/project/simple_jsonpath/>
- <https://github.com/seojumper/simple_jsonpath/releases>
- <https://pypi.org/project/aero-jmespath/>
- <https://github.com/SereinCin/aero-ecosystem>
- <https://pypi.org/project/jmespath/>
- <https://github.com/jmespath/jmespath.py>
- <https://pypi.org/project/jsonpath2/>
- <https://github.com/pacifica/python-jsonpath2>
- <https://pypi.org/project/jsonpath-rw/>
- <https://github.com/kennknowles/python-jsonpath-rw>
- <https://pypi.org/project/jsonpath-rw-ext/>
- <https://github.com/sileht/python-jsonpath-rw-ext>
