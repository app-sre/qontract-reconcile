# ADR-019: Merge Queue Acceleration via Optimistic Non-Overlapping Multi-Merge

**Status:** Proposed
**Date:** 2026-03-03
**Updated:** 2026-03-05
**Authors:** @TGPSKI
**Reviewers:** @jfchevrette, @fenghuang, @wangdi

## Context

The `gitlab-housekeeping` integration manages merge request lifecycle for app-interface and other repositories. For repos with `rebase: true` (including app-interface), the current merge flow is strictly serial:

1. Rebase up to `limit` MRs onto the target branch
2. Wait for the first pipeline to succeed (`insist` retry loop)
3. Merge exactly one MR
4. `return` immediately -- all other rebased MRs are now invalid

After merging MR-A, the target branch HEAD changes. The `is_rebased()` check compares the MR's SHA against the target branch HEAD, so every other rebased MR fails this check and must be re-rebased, triggering new pipelines. The result is one merge per pipeline-duration cycle (~10 minutes), regardless of the `limit` config.

With app-interface's `limit: 2` and ~8 minute pipelines, the maximum throughput is ~7 MRs/hour. During sustained load (10+ MRs queued), low-priority MRs (e.g. `lgtm` label) experience starvation -- they are perpetually pushed to future reconcile loops by higher-priority MRs that consume all rebase and merge slots.

### Why increasing the limit alone does not help

The serial dependency is structural, not configurational. Bumping `limit` from 2 to 8 means 8 MRs get rebased instead of 2, but after the first merge changes the target branch, the other 7 are invalidated and need re-rebase. The throughput remains 1 merge per cycle.

### How GitLab merge trains solve this

GitLab merge trains run MR-B's pipeline against `target + A + B` speculatively, in parallel with MR-A's pipeline. When MR-A merges, MR-B's pipeline is already validated against the correct base. This requires GitLab Premium licensing and GitLab CI runners, which would mean replacing the current Jenkins infrastructure.

## Decision

**Implement optimistic non-overlapping multi-merge in `gitlab_housekeeping.py`: after the first merge in a loop, merge subsequent MRs if their changed files -- expanded to include `$ref` crossref targets and backrefs -- do not overlap with any already-merged MR's expanded file set.**

### Key Points

- The first MR in each loop iteration still requires `is_rebased()` and a passing pipeline (unchanged safety)
- Subsequent MRs skip the `is_rebased()` check if their expanded changed file paths have zero intersection with the union of all previously merged MRs' expanded file paths
- **Overlap detection is reference-aware:** each MR's changed paths are expanded to include files referenced via `$ref` crossrefs and files that reference the changed files (backrefs). This prevents merging semantically coupled but file-disjoint changes (see "Why file-level overlap is not enough" below)
- **Optimistic MRs are rebased with `skip_ci=True` before merge** to satisfy fast-forward merge requirements without triggering redundant pipelines
- The `if rebase: return` exit after a single merge is removed, allowing multiple merges per loop
- `limit` is redefined as a per-repo cap (not per-run) controlling the steady-state number of rebased MRs with active pipelines
- A circuit breaker prevents zombie MRs (repeated pipeline failures) from blocking the queue
- New Prometheus metrics track optimistic merge success rate and overlap frequency

### Why file-level overlap is not enough

Raw file-path intersection misses cross-file semantic dependencies that exist via `$ref` crossrefs in app-interface datafiles. Two concrete examples:

1. **Namespace + resource parameter:** MR-A changes `data/services/foo/namespaces/bar.yml` (adds an external resource reference), MR-B changes `resources/services/foo/some-config.yml` (the resource template). Different files, but the namespace file references the resource via `$ref`. Changes from MR-A may conflict with MR-B's resource content, but file-level overlap would not detect this.

2. **Role/permission + user:** MR-A changes `data/access/roles/some-role.yml` (modifies permissions), MR-B changes `data/access/users/some-user.yml` (adds a `$ref` to that role). A reviewer approved MR-B based on the *old* permissions in the role. If MR-A merges first, the user effectively gets different permissions than what was reviewed.

The solution is to expand each MR's changed paths to include its `$ref` dependency neighborhood (see Implementation Guidelines).

### Rationale

Most app-interface MRs modify independent YAML datafiles under different service directories. When MR-A changes `data/services/foo/app.yml` and MR-B changes `data/services/bar/deploy.yml`, MR-B's pipeline result against `old_master` is identical to its result against `old_master + MR-A`. The file contents, schema validation, and integration dry-runs are all independent.

With reference-aware overlap detection, the safety guarantee extends to cross-file dependencies: if two MRs touch files that are connected by `$ref` crossrefs (directly or transitively), they are treated as overlapping and fall back to serial merge. This eliminates the class of semantic conflicts identified in review while preserving the throughput benefit for the majority of MRs that are truly independent.

This approach gets 60-70% of the throughput benefit of GitLab merge trains with no infrastructure changes.

### Relationship to Existing Changed-Path Analysis

Several integrations already analyze which files an MR changes. This ADR's overlap detection reuses existing utilities rather than introducing new mechanisms:

- **`GitLabApi.get_merge_request_changed_paths()`** (`reconcile/utils/gitlab_api.py:398`) is the shared method that calls the GitLab MR changes API. It is already used by `gitlab_owners` (for CODEOWNERS-style approval routing), `gitlab_labeler` (for `tenant-*` label assignment), and `openshift_saas_deploy_change_tester` (for filtering saas-file diffs). This ADR's overlap detection reuses the same method as the starting point for path expansion.

- **`gitlab_labeler`** already applies `tenant-*` labels (e.g. `tenant-foo`) based on which `data/services/` directories an MR touches. These labels are present on the MR by the time `gitlab_housekeeping` runs. A coarse overlap check could compare `tenant-*` labels between MRs with zero additional API calls. However, tenant labels are too imprecise: two MRs touching different files under the same service directory (e.g. `app.yml` vs `deploy.yml`) would incorrectly appear to overlap.

- **change-owners** uses a different mechanism entirely: the qontract-server `/diff` endpoint compares two bundle SHAs. This provides deep semantic diff information (per-field changes, change-type coverage), but requires a running qontract-server with loaded bundles and is not available in the housekeeping merge loop context.

### Reference-Aware Path Expansion

Raw file paths from `get_merge_request_changed_paths()` are expanded using a reference graph built from the bundle's datafiles. For each changed file, the expanded set includes:

1. **The file itself** (direct change)
2. **Forward refs:** files referenced by the changed file via `$ref` crossrefs (e.g., a namespace file's `cluster`, `app`, `environment` refs)
3. **Backward refs:** files that reference the changed file (e.g., if a role file changes, all user files that `$ref` that role are included)

The reference graph can be built by traversing all datafiles in the bundle and collecting `$ref` pointers. The bundle is already loaded in memory by qontract-server and available via the `/graphql` endpoint. Two implementation approaches:

- **Bundle-local:** Load the bundle JSON directly in `gitlab_housekeeping` and traverse datafiles to build the ref graph. This is self-contained but adds memory and startup cost.
- **qontract-server query:** Query the GraphQL API for synthetic backref fields and forward refs. This reuses existing infrastructure but adds network calls.
- **Pre-computed lookup table:** Build the reference graph as a periodic job (or as part of bundle validation) and store it as a JSON artifact. `gitlab_housekeeping` loads this artifact at startup. This is the most efficient at runtime.

The recommended approach is the pre-computed lookup table, built during bundle validation and stored alongside the bundle. This adds zero runtime overhead to the merge loop beyond a dictionary lookup.

The expansion depth should be configurable (default: 1 hop). For most app-interface patterns, 1-hop expansion (direct refs and backrefs) is sufficient. Deeper transitive expansion increases safety but also increases the overlap rate, reducing throughput.

## Alternatives Considered

### Alternative 1: GitLab Merge Trains (Native)

Migrate from Jenkins CI to GitLab CI runners and enable GitLab merge trains. GitLab speculatively validates each MR against the cumulative changes of all preceding MRs.

**Pros:**

- Maximum throughput (50+ MRs/hour)
- Zero risk of broken master (full speculative validation)
- No custom merge logic to maintain

**Cons:**

- Requires GitLab Premium licensing
- Requires migrating CI from Jenkins to GitLab CI runners
- Requires managing a private GitLab runner fleet to replace Jenkins EC2 spot autoscaling
- 4-8 week implementation timeline for infrastructure migration

### Alternative 2: DIY Speculative Merge Train

Build a full merge train in `gitlab_housekeeping.py` by creating temporary branches that stack MRs (`train/pos-0` = master + A, `train/pos-1` = master + A + B) and triggering Jenkins jobs against those branches.

**Pros:**

- Full speculative validation (same safety as GitLab merge trains)
- Uses existing Jenkins infrastructure

**Cons:**

- Significant complexity: temporary branch lifecycle, train state persistence across reconcile loops, cascade invalidation when mid-train MRs fail
- Requires Jenkins job parameterization to accept arbitrary branches
- Requires changes to `pr_check.sh` to validate against speculative branches instead of master
- High ongoing maintenance burden

### Alternative 3: Serial Queue Hardening (Wang Di's Proposal)

Keep the serial one-merge-per-cycle model but improve queue hygiene:

- Require last pipeline to pass before adding MR to merge queue
- Redefine `limit` as a per-repo cap (not per-run) and keep it small (1-3) to reduce wasted CI from over-rebasing across rapid reconcile cycles
- Label MRs that fail to merge for an "error queue" and remove from active queue
- Handle corner cases (pipeline pass + approved but merge fails due to GitLab issues)

**Pros:**

- Zero risk of broken master (serial merge preserved)
- Addresses wasted CI from over-rebasing
- Simple to implement, no new concepts
- Handles operational edge cases not currently covered

**Cons:**

- Does not break the serial throughput ceiling (~7 MRs/hour)
- Priority starvation persists under sustained load
- Does not address the fundamental bottleneck

**Assessment:** These are valuable operational improvements that should be adopted as Phase 0 regardless of which acceleration strategy is selected. They complement rather than replace multi-merge.

### Alternative 4: Optimistic Non-Overlapping Multi-Merge (Selected)

After the first merge, allow subsequent non-overlapping MRs to merge with `skip_ci` rebase. Overlap detection is reference-aware, using `$ref` crossref expansion to catch semantic dependencies between file-disjoint MRs.

**Pros:**

- No infrastructure changes (keeps Jenkins, no licensing changes)
- Reference-aware overlap detection prevents the class of semantic conflicts identified in review (namespace+resource, role+user)
- Uses existing `GitLabApi.get_merge_request_changed_paths()` API plus bundle reference graph
- Safe fallback: overlapping MRs are deferred to re-rebase (no regression)
- Projected 10-20 MRs/hour for typical non-overlapping workloads
- 2-3 week implementation timeline
- New metrics provide data to justify further investment if needed

**Cons:**

- Reference-aware expansion increases the overlap rate compared to raw file-level detection, reducing throughput gain
  - **Mitigation:** Most app-interface MRs touch independent service directories with no cross-refs; the `optimistic_merge_rejected_total` metric quantifies the effective overlap rate
- Requires building and maintaining a reference graph from the bundle
  - **Mitigation:** The graph is derived from existing bundle data and can be pre-computed during validation
- Residual risk of broken master for dependencies not captured by `$ref` (e.g. two MRs that independently add conflicting YAML keys to different files consumed by the same integration)
  - **Mitigation:** Post-merge master pipeline catches this immediately. This risk class is narrow and equivalent to "merge when pipeline succeeds" workflows

## Consequences

### Positive

- Throughput increase from ~7 MRs/hour to ~10-20 MRs/hour for typical workloads (see throughput analysis below)
- Eliminates priority starvation: lower-priority MRs progress within the same loop iteration
- Reference-aware overlap detection prevents the class of semantic conflicts identified in review (crossref dependencies between file-disjoint MRs)
- Per-repo `limit` semantics give operators fine-grained control over pipeline concurrency and queue behavior
- Phase 0 queue hardening (error labeling, pipeline-must-pass filtering) improves reliability regardless of multi-merge
- Circuit breaker prevents zombie MRs from blocking the queue
- New metrics provide visibility into merge queue health and overlap rates
- No infrastructure changes, licensing costs, or CI migration

### Negative

- Reference-aware path expansion increases the effective overlap rate compared to raw file-level detection, reducing throughput gain
  - **Mitigation:** The `optimistic_merge_rejected_total` metric tracks overlap rate by reason. If ref-expansion causes excessive overlap, the expansion depth can be tuned or the two-tier approach (tenant labels first, then API) can reduce false positives.
- Residual risk of broken master for dependencies not captured by `$ref` crossrefs
  - **Mitigation:** Post-merge master pipeline detects this. The risk class is narrow (non-`$ref` semantic coupling between independent files) and equivalent to "merge when pipeline succeeds" workflows.
- Additional GitLab API calls per MR (`get_merge_request_changed_paths`) in the merge loop
  - **Mitigation:** One API call per MR candidate. With `merge_limit: 6`, this is at most 6 additional calls per loop.
- Requires building and maintaining a reference graph from the bundle
  - **Mitigation:** Pre-computed during bundle validation and stored as a JSON artifact. Runtime cost is a dictionary lookup.
- If overlap rate exceeds 40%, the approach degrades toward serial behavior
  - **Mitigation:** The `optimistic_merge_rejected_total` metric tracks this. If overlap rate is consistently high, escalate to Alternative 2 (speculative train).

## Implementation Guidelines

### Phase 0: Queue Hardening and Config Tuning (immediate)

Operational improvements that reduce wasted CI and improve reliability, independent of multi-merge:

1. **Redefine `limit` as a per-repo cap, not per-run.** Currently `limit` controls how many MRs are rebased *per reconcile run*, with the counter resetting each invocation. Since `gitlab-housekeeping` runs frequently (~1 min cycles), a `limit: 2` still results in many MRs being rebased across runs, each triggering a pipeline -- most of which are wasted when only one MR merges per cycle. The fix: change the semantics so `limit` means "at most N MRs should be in a rebased-and-pipeline-pending state at any time for this repo." Before rebasing, count how many MRs already have running or recent pipelines and only rebase up to `limit - already_active`. Keep `limit` small (2-3) to minimize wasted CI. This is a prerequisite for Phase 1: with per-repo semantics, bumping `limit` to 6 for multi-merge becomes safe because it controls the *steady-state pipeline concurrency*, not the per-run rebase burst.

2. **Filter MRs with failed pipelines from the merge queue.** Move the pipeline-success check from `merge_merge_requests` into `preprocess_merge_requests` so MRs without a passing last pipeline are excluded before sorting and slot allocation. This prevents failed MRs from consuming rebase slots.

3. **Label MRs that fail to merge repeatedly.** When `mr.merge()` raises an exception (beyond `GitlabMRClosedError`), catch `GitlabOperationError` and apply a label (e.g. `merge-error`) to the MR. Exclude MRs with this label from the merge queue. This creates a visible "error queue" for manual triage and prevents stuck MRs from blocking the queue.

4. **Broaden merge exception handling.** Currently only `GitlabMRClosedError` is caught. Add `GitlabOperationError` to handle fast-forward rejection, pipeline-gated rejection, branch-missing, and other server-side refusals gracefully. Note: python-gitlab does not have a `GitlabMergeError` class; `GitlabOperationError` is the common parent of all MR-related exceptions (`GitlabMRClosedError`, `GitlabMRForbiddenError`, `GitlabMROnBuildSuccessError`, etc.).

### Phase 1: Optimistic Multi-Merge (2-3 weeks)

#### 1. Add `merge_limit` to the housekeeping schema in qontract-schemas

The schema must support an optional `merge_limit` field alongside the existing `limit`. `limit` controls the per-repo pipeline concurrency cap (how many MRs can be in a rebased-and-pipeline-pending state). `merge_limit` controls how many MRs can be merged per loop iteration (relevant for multi-merge). When absent, `merge_limit` defaults to `limit`.

#### 2. Build reference graph from bundle

Build a lookup table mapping each datafile path to its expanded dependency neighborhood:

```python
def build_ref_graph(bundle: dict) -> dict[str, set[str]]:
    """Build forward and backward ref maps from bundle datafiles."""
    forward_refs: dict[str, set[str]] = defaultdict(set)
    backward_refs: dict[str, set[str]] = defaultdict(set)

    for path, datafile in bundle["data"].items():
        for ref_target in extract_refs(datafile):
            forward_refs[path].add(ref_target)
            backward_refs[ref_target].add(path)

    expanded: dict[str, set[str]] = {}
    for path in bundle["data"]:
        expanded[path] = {path} | forward_refs.get(path, set()) | backward_refs.get(path, set())
    return expanded
```

This graph is pre-computed once per bundle load and passed into the merge loop. `extract_refs()` recursively walks the datafile JSON and collects all `{"$ref": "..."}` target paths.

#### 3. Implement reference-aware overlap detection

```python
def expand_paths(
    raw_paths: set[str], ref_graph: dict[str, set[str]]
) -> set[str]:
    """Expand raw changed paths to include $ref neighbors."""
    expanded = set()
    for p in raw_paths:
        expanded.update(ref_graph.get(p, {p}))
    return expanded

def get_changed_paths(
    mr: ProjectMergeRequest, gl: GitLabApi, ref_graph: dict[str, set[str]]
) -> set[str]:
    raw = set(gl.get_merge_request_changed_paths(mr))
    return expand_paths(raw, ref_graph)

def has_overlapping_changes(
    mr_paths: set[str], merged_paths: set[str]
) -> bool:
    return bool(mr_paths & merged_paths)
```

#### 4. Modify `merge_merge_requests()` merge loop

This is the most complex change. There are four interacting concerns:

**The `@retry` / `InsistOnPipelineError` interaction.** The current function is decorated with `@retry(max_attempts=10)`. When `insist=True` and a pipeline is still running, it raises `InsistOnPipelineError`, which restarts the entire function from the top. Any local state (`merged_paths`, `first_merge_done`) is lost on retry. The `insist` mechanism is effectively a polling loop that waits for the *first* rebased MR's pipeline to complete.

The solution: the `insist` wait-and-retry behavior only applies *before* the first merge. Once we have merged at least one MR, we stop waiting for running pipelines and only consider MRs whose pipelines have already completed successfully. This avoids the retry blowing away the multi-merge state, because we never raise `InsistOnPipelineError` after the first merge. Concretely, `wait_for_pipeline` with `insist` is only checked when `first_merge_done is False`.

**Fast-forward merge requires rebase.** App-interface uses fast-forward merge. After the first merge changes the target branch, subsequent MRs are no longer rebased and `mr.merge()` will be rejected. The solution: call `mr.rebase(skip_ci=True)` before `mr.merge()` for optimistic MRs. This rebases the MR onto the new target HEAD without triggering a new pipeline, allowing the fast-forward merge to proceed. The existing pipeline result is still valid because the MR's changes do not overlap with the merged changes (guaranteed by the overlap check).

**Merge rejection handling.** Even with `skip_ci` rebase, the merge may fail for other reasons (race conditions, GitLab transient errors). The python-gitlab library raises `GitlabOperationError` (or a subclass like `GitlabMRClosedError`, `GitlabMROnBuildSuccessError`) on rejection. The exception handler must catch `GitlabOperationError` broadly and treat rejection as a skip.

**Caching changed paths.** `get_merge_request_changed_paths()` calls the GitLab API. The overlap check and the `merged_paths` update both need the paths for the same MR. Cache the result to avoid a redundant API call.

```python
merged_paths: set[str] = set()
first_merge_done = False
paths_cache: dict[int, set[str]] = {}

for merge_request in merge_requests:
    mr = merge_request["mr"]

    if rebase:
        if first_merge_done:
            if mr.iid not in paths_cache:
                paths_cache[mr.iid] = get_changed_paths(mr, gl, ref_graph)
            if has_overlapping_changes(paths_cache[mr.iid], merged_paths):
                optimistic_merge_rejected.labels(
                    project_id=mr.target_project_id, reason="overlap"
                ).inc()
                continue
        else:
            if not is_rebased(mr, gl):
                continue

    pipelines = gl.get_merge_request_pipelines(mr)
    if not pipelines:
        continue

    # Pipeline timeout cleanup (unchanged) ...

    if not first_merge_done and wait_for_pipeline:
        running_pipelines = [
            p for p in pipelines if p.status == PipelineStatus.RUNNING
        ]
        if running_pipelines:
            if insist:
                reload_toggle.reload = True
                raise InsistOnPipelineError(...)
            continue
    elif first_merge_done:
        # After first merge, only consider MRs with completed pipelines.
        # Do NOT raise InsistOnPipelineError -- that would reset our state.
        if pipelines[0].status == PipelineStatus.RUNNING:
            continue

    last_pipeline_result = pipelines[0].status
    if last_pipeline_result != PipelineStatus.SUCCESS:
        continue

    if not dry_run and merges < merge_limit:
        try:
            squash = (
                gl.project.squash_option == SQUASH_OPTION_ALWAYS
            ) or mr.squash

            if first_merge_done and rebase:
                # Rebase onto new target HEAD without triggering pipeline.
                # Safe because overlap check guarantees no file conflicts.
                mr.rebase(skip_ci=True)

            mr.merge(squash=squash)
            if mr.iid not in paths_cache:
                paths_cache[mr.iid] = get_changed_paths(mr, gl, ref_graph)
            merged_paths.update(paths_cache[mr.iid])
            if first_merge_done:
                optimistic_merges.labels(mr.target_project_id).inc()
            first_merge_done = True
            merges += 1
            # ... existing metrics (merged_merge_requests, time_to_merge) ...
        except gitlab.exceptions.GitlabMRRebaseError as e:
            logging.warning(
                f"optimistic rebase failed for {mr.iid}: {e}"
            )
            optimistic_merge_rejected.labels(
                project_id=mr.target_project_id, reason="rebase_failed"
            ).inc()
        except gitlab.exceptions.GitlabMRClosedError as e:
            logging.error(f"unable to merge {mr.iid}: {e}")
        except gitlab.exceptions.GitlabOperationError as e:
            logging.warning(
                f"optimistic merge rejected for {mr.iid}: {e}"
            )
            optimistic_merge_rejected.labels(
                project_id=mr.target_project_id, reason="merge_rejected"
            ).inc()

merge_batch_size_histogram.labels(gl.project.id).observe(merges)
```

**Key design constraints:**

- `InsistOnPipelineError` is only raised before the first merge (`not first_merge_done`). After the first merge, running pipelines are silently skipped. This ensures the retry decorator never resets multi-merge state.
- `mr.rebase(skip_ci=True)` is called before `mr.merge()` for optimistic MRs to satisfy fast-forward merge requirements. The `skip_ci` flag prevents a redundant pipeline. `GitlabMRRebaseError` is caught separately to distinguish rebase failures from merge failures.
- The `insist=False` fallback call in `run()` works correctly: it never raises `InsistOnPipelineError` regardless, so the multi-merge loop runs without interruption.
- `GitlabOperationError` is the common parent of all MR-related exceptions in python-gitlab (`GitlabMRClosedError`, `GitlabMRForbiddenError`, `GitlabMROnBuildSuccessError`, etc.). Catching it after `GitlabMRClosedError` covers fast-forward rejection, pipeline-gated rejection, and other server-side refusals.
- `paths_cache` avoids calling `get_merge_request_changed_paths()` twice for the same MR (once for the overlap check, once for updating `merged_paths` after merge).
- The `ref_graph` is loaded once at the start of the merge loop from the pre-computed artifact (see step 2).

#### 5. Wire up per-repo `limit` and `merge_limit` in `run()`

```python
limit = hk.get("limit") or default_limit  # per-repo pipeline concurrency cap
merge_limit = hk.get("merge_limit") or limit  # max merges per loop iteration
```

In `rebase_merge_requests`, count MRs that already have running/recent pipelines and only rebase up to `limit - already_active`.

#### 6. Add circuit breaker for zombie MRs

Track consecutive pipeline failures per MR IID in `State`. After 3 consecutive failures, skip the MR for the current loop and log a warning. Reset the counter when the MR's pipeline succeeds or a new commit is pushed.

#### 7. Add Prometheus metrics

- `optimistic_merges_total` (Counter, labels: `project_id`) -- MRs merged via the optimistic non-overlapping path
- `optimistic_merge_rejected_total` (Counter, labels: `project_id`, `reason`) -- MRs skipped due to file overlap or GitLab merge rejection
- `merge_batch_size` (Histogram, labels: `project_id`) -- number of MRs merged per loop iteration

### Throughput Analysis

**Current state:** 1 merge per cycle. Cycle time = pipeline duration (~8 min) + insist retry overhead (~1 min) + reconcile sleep (~1 min) = ~10 min. Throughput: ~6 MRs/hour.

**With optimistic multi-merge:** The first merge still takes ~10 min (waiting for pipeline via insist). After the first merge, additional MRs whose pipelines have already completed can merge after a `skip_ci` rebase (seconds per merge). Since all rebased MRs start pipelines at roughly the same time, most finish within a narrow window around the 8-minute mark.

With a per-repo `limit: 6` (meaning 6 MRs in a rebased-and-pipeline-pending state at any time) and reference-aware overlap detection, the effective non-overlapping rate depends on the MR mix. Reference expansion increases the overlap surface compared to raw file-level detection -- MRs touching files that share `$ref` crossrefs will be flagged even if the files themselves are different.

**Assumptions:**

- 60-70% of queued MRs are truly independent (no shared `$ref` neighborhood) -- lower than the 80% raw file estimate due to ref expansion
- Pipeline time variance: 6-10 minutes, with most completing within 1-2 minutes of each other
- `skip_ci` rebase takes ~2-5 seconds per MR (GitLab API call, no pipeline trigger)
- Jenkins has sufficient executor capacity for 6 parallel pipelines (spot autoscaling)

**Projections:**

- **Conservative estimate:** 1 (first) + 2 (optimistic) = 3 merges per 10-min cycle = **~18 MRs/hour**
- **Optimistic estimate:** 1 + 4 = 5 per cycle = **~30 MRs/hour**
- **Realistic midpoint:** ~10-20 MRs/hour, depending on pipeline time variance, overlap rate, and `skip_ci` rebase reliability

Even the conservative estimate represents a ~3x improvement over the current ~6 MRs/hour ceiling.

### Phase 2: Speculative Stacking (conditional)

Only pursue if Phase 1 metrics show overlap rate exceeding 30%. This phase involves temporary branch creation, Jenkins job parameterization, and cascade invalidation logic. Defer design until Phase 1 data is available.

### Checklist

**Phase 0:**

- [ ] Redefine `limit` as per-repo cap (count already-active pipelines before rebasing)
- [ ] Broaden merge exception handling to catch `GitlabOperationError`
- [ ] Add error-queue labeling for MRs that fail to merge repeatedly
- [ ] Move pipeline-success check into `preprocess_merge_requests`

**Phase 1:**

- [ ] Add `merge_limit` to housekeeping schema in qontract-schemas
- [ ] Build reference graph from bundle (`build_ref_graph()`)
- [ ] Implement `expand_paths()`, `get_changed_paths()`, and `has_overlapping_changes()`
- [ ] Replace the single-merge `return` with reference-aware multi-merge loop
- [ ] Add `mr.rebase(skip_ci=True)` for optimistic MRs before merge
- [ ] Verify `skip_ci` parameter support in python-gitlab `mr.rebase()`
- [ ] Wire up per-repo `limit` and `merge_limit` in `run()` (backward compatible)
- [ ] Add circuit breaker with `State` tracking
- [ ] Add `optimistic_merges_total`, `optimistic_merge_rejected_total`, `merge_batch_size` metrics
- [ ] Add unit tests for overlap detection, ref expansion, and multi-merge behavior
- [ ] Set `limit: 6` (per-repo cap) in app-interface `app.yml` once per-repo semantics are in place
- [ ] Monitor `optimistic_merge_rejected_total` for overlap rate after rollout

## References

- Implementation: `reconcile/gitlab_housekeeping.py` -- merge loop, rebase logic, priority sorting
- Implementation: `reconcile/utils/gitlab_api.py:398` -- `get_merge_request_changed_paths()`
- Implementation: `reconcile/utils/state.py` -- `State` for circuit breaker persistence
- Crossrefs: `qontract-schemas/schemas/common-1.json` -- `$ref` crossref definition
- Crossrefs: `qontract-validator/validator/validator.py` -- `validate_ref()` crossref resolution
- App-interface config: `data/services/app-interface/app.yml` -- `gitlabHousekeeping.limit`
- CI pipeline: `hack/pr_check.sh`, `hack/manual_reconcile.sh`, `hack/select-integrations.py`
- External: [GitLab merge trains](https://docs.gitlab.com/ci/pipelines/merge_trains/)
- External: [GitLab merge_ref API](https://docs.gitlab.com/api/merge_requests/#merge-to-default-merge-ref-path)
- External: [python-gitlab MR rebase](https://python-gitlab.readthedocs.io/en/stable/gl_objects/merge_requests.html) -- `mr.rebase(skip_ci=True)`
