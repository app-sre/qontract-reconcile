# ADR-019: Merge Queue Acceleration via Optimistic Non-Overlapping Multi-Merge

**Status:** Accepted
**Date:** 2026-03-03
**Updated:** 2026-04-13
**Authors:** @TGPSKI
**Reviewers:** @jfchevrette, @fenghuang, @wangdi, @chassing, @fishi0x01, @mafriedm

## Context

The `gitlab-housekeeping` integration manages merge request lifecycle for app-interface and other repositories. For repos with `rebase: true` (including app-interface), the current merge flow is strictly serial:

1. Rebase up to `limit` MRs onto the target branch
2. Wait for the first pipeline to succeed (`insist` retry loop)
3. Merge exactly one MR
4. `return` immediately -- all other rebased MRs are now invalid

After merging MR-A, the target branch HEAD changes. The `is_rebased()` check compares the MR's SHA against the target branch HEAD, so every other rebased MR fails this check and must be re-rebased, triggering new pipelines. The result is one merge per pipeline-duration cycle (~10 minutes), regardless of the `limit` config.

With app-interface's `limit: 2` and ~8 minute pipelines, the measured serial throughput is ~7.9 MRs/hour (empirically measured from a 6h 52m production pod log on 2026-03-03, see Throughput Analysis). During sustained load (10+ MRs queued), low-priority MRs (e.g. `lgtm` label) experience starvation -- they are perpetually pushed to future reconcile loops by higher-priority MRs that consume all rebase and merge slots. In the observed log, MR 177008 was starved for over 3h 51m despite having `lgtm`, never merging while 53 other MRs merged ahead of it.

### Why increasing the limit alone does not help

The serial dependency is structural, not configurational. Bumping `limit` from 2 to 8 means 8 MRs get rebased instead of 2, but after the first merge changes the target branch, the other 7 are invalidated and need re-rebase. The throughput remains 1 merge per cycle.

### How GitLab merge trains solve this

GitLab merge trains run MR-B's pipeline against `target + A + B` speculatively, in parallel with MR-A's pipeline. When MR-A merges, MR-B's pipeline is already validated against the correct base. This requires GitLab Premium licensing and GitLab CI runners, which would mean replacing the current Jenkins infrastructure.

## Decision

**Implement optimistic non-overlapping multi-merge in `gitlab_housekeeping.py`: after the first merge in a loop, merge subsequent MRs if their `tenant-*` labels do not overlap with any already-merged MR's labels. Only MRs with at least one `tenant-*` label are eligible for optimistic merge.**

### Key Points

- The first MR in each loop iteration still requires `is_rebased()` and a passing pipeline (unchanged safety)
- **Eligibility gate:** only MRs with at least one `tenant-*` label are candidates for optimistic merge. MRs without `tenant-*` labels (global infrastructure changes, cross-cutting refactors) have no label to compare and fall back to serial processing. MRs with many `tenant-*` labels (e.g. qr-bump touching dozens of services) are naturally serialized by the overlap check itself
- **Overlap detection via `tenant-*` labels:** subsequent MRs skip the `is_rebased()` check if their `tenant-*` label set has zero intersection with the union of all previously merged MRs' `tenant-*` labels. Labels are already applied by `gitlab_labeler` before housekeeping runs -- zero additional API calls
- **Optimistic MRs are rebased with `skip_ci=True` before merge** to satisfy fast-forward merge requirements without triggering redundant pipelines
- The `if rebase: return` exit after a single merge is removed, allowing multiple merges per loop
- `limit` is redefined as a per-repo cap (not per-run) controlling the steady-state number of rebased MRs with active pipelines
- A healthcheck-probe model prevents zombie MRs (repeated pipeline failures) from blocking the queue: check the last N pipelines (already fetched via `gl.get_merge_request_pipelines(mr)`) for consecutive failures, then apply a `merge-error` label to flag the MR in the existing merge queue rendering for IC triage
- New Prometheus metrics track optimistic merge success rate and overlap frequency

### Why file-level overlap is not enough -- and why we chose labels

Raw file-path intersection misses cross-file semantic dependencies that exist via `$ref` crossrefs in app-interface datafiles. Two concrete examples:

1. **Namespace + resource parameter:** MR-A changes `data/services/foo/namespaces/bar.yml` (adds an external resource reference), MR-B changes `resources/services/foo/some-config.yml` (the resource template). Different files, but the namespace file references the resource via `$ref`. Changes from MR-A may conflict with MR-B's resource content, but file-level overlap would not detect this.

2. **Role/permission + user:** MR-A changes `data/access/roles/some-role.yml` (modifies permissions), MR-B changes `data/access/users/some-user.yml` (adds a `$ref` to that role). A reviewer approved MR-B based on the *old* permissions in the role. If MR-A merges first, the user effectively gets different permissions than what was reviewed.

A reference-graph approach (expanding changed paths by `$ref` forward/backward refs) was considered but has a fatal flaw: the production bundle does not contain files introduced by MR branches. If MR-A adds a new file with a `$ref` to an existing role, the reference graph built from master's bundle will not include that forward ref. The overlap check would miss it, undermining the safety guarantee. Fixing this would require fetching each MR's branch content and rebuilding the graph per-MR, dramatically increasing complexity (see Alternative 5).

**The chosen approach uses `tenant-*` labels as a coarser but provably safe boundary.** Labels are computed per-MR from actual changed files by `gitlab_labeler`. Two MRs with non-overlapping `tenant-*` labels are guaranteed to touch different service directories, which inherently avoids the crossref conflicts above (both examples involve files under the same service). This trades some throughput (same-service MRs are serialized even if they touch different files) for simplicity and correctness.

### Rationale

Most app-interface MRs modify independent YAML datafiles under different service directories. When MR-A changes `data/services/foo/app.yml` and MR-B changes `data/services/bar/deploy.yml`, MR-B's pipeline result against `old_master` is identical to its result against `old_master + MR-A`. The file contents, schema validation, and integration dry-runs are all independent.

Using `tenant-*` labels as the overlap boundary provides service-level isolation: MRs touching different services are guaranteed independent by directory structure, and `$ref` crossrefs that create semantic coupling (namespace+resource, role+user) are contained within the same service directory. This eliminates the class of semantic conflicts identified in review while preserving the throughput benefit for the majority of MRs that touch different services.

The label-based approach has key advantages over finer-grained alternatives:

- **Zero API calls** -- labels are already present on the MR from `gitlab_labeler`
- **Safe by construction** -- service-level isolation is a strong boundary that captures `$ref` crossref dependencies without needing to build or maintain a reference graph
- **~50 lines of Python** -- dramatically simpler than reference-graph or change-type approaches
- **Already available** -- no new infrastructure, no bundle loading, no qontract-server dependency

This approach gets 50-60% of the throughput benefit of GitLab merge trains with no infrastructure changes. Future refinement via change-type coverage (Phase 2) can unlock same-service multi-merge if metrics show high overlap rates.

### Relationship to Existing Changed-Path Analysis

Several integrations already analyze which files an MR changes. This ADR's overlap detection builds on existing infrastructure:

- **`gitlab_labeler`** already applies `tenant-*` labels (e.g. `tenant-foo`) based on which `data/services/` directories an MR touches. These labels are present on the MR by the time `gitlab_housekeeping` runs. **This is the primary overlap detection mechanism for this ADR:** compare `tenant-*` labels between MRs with zero additional API calls. Two MRs touching different files under the same service (e.g. `app.yml` vs `deploy.yml`) are treated as overlapping -- this is intentionally conservative to avoid the crossref pitfalls described above.

- **`GitLabApi.get_merge_request_changed_paths()`** (`reconcile/utils/gitlab_api.py`) is the shared method that calls the GitLab MR changes API. It is used by `gitlab_owners`, `gitlab_labeler`, and `openshift_saas_deploy_change_tester`. It is not directly used for overlap detection in this ADR (labels are sufficient), but remains available for future finer-grained approaches.

- **change-owners** uses a different mechanism: the qontract-server `/diff` endpoint compares two bundle SHAs. This provides deep semantic diff information (per-field changes, change-type coverage), but requires a running qontract-server with loaded bundles and is not available in the housekeeping merge loop context. See Phase 2 for how change-type coverage could be used as a future refinement.

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
- Flag MRs that fail to merge with `merge-error` label in the existing merge queue rendering
- Handle corner cases (pipeline pass + approved but merge fails due to GitLab issues)

**Pros:**

- Zero risk of broken master (serial merge preserved)
- Addresses wasted CI from over-rebasing
- Simple to implement, no new concepts
- Handles operational edge cases not currently covered

**Cons:**

- Does not break the serial throughput ceiling (~8 MRs/hour measured)
- Priority starvation persists under sustained load
- Does not address the fundamental bottleneck

**Assessment:** These are valuable operational improvements that should be adopted as Phase 0 regardless of which acceleration strategy is selected. They complement rather than replace multi-merge.

### Alternative 4: Optimistic Non-Overlapping Multi-Merge with Label-Based Overlap (Selected)

After the first merge, allow subsequent non-overlapping MRs to merge with `skip_ci` rebase. Overlap detection uses `tenant-*` labels (applied by `gitlab_labeler`) as the isolation boundary. Only MRs with at least one `tenant-*` label are eligible for optimistic merge.

**Pros:**

- No infrastructure changes (keeps Jenkins, no licensing changes)
- Label-based overlap is safe by construction: service-level isolation captures `$ref` crossref dependencies without needing a reference graph
- Zero additional API calls for overlap detection (labels are already present)
- ~50 lines of Python -- dramatically simpler than ref-graph or change-type approaches
- `tenant-*` label eligibility gate: MRs without labels fall back to serial; MRs touching many services are naturally serialized by overlap
- Safe fallback: same-service MRs are serialized (no regression)
- Projected 10-20 MRs/hour for typical cross-service workloads
- 1-2 week implementation timeline
- New metrics provide data to justify further investment (Phase 2 change-type refinement)

**Cons:**

- Coarser than file-level detection: two MRs touching different files under the same service are treated as overlapping
  - **Mitigation:** Most concurrent MRs touch different services. The `optimistic_merge_rejected_total` metric tracks overlap rate. If same-service overlap is high, Phase 2 (change-type refinement) can unlock finer-grained detection.
- Residual risk of broken master for dependencies not captured by service-level isolation (e.g. cross-service `$ref` chains)
  - **Mitigation:** Cross-service `$ref`s are rare in app-interface. Post-merge master pipeline catches this immediately. This risk class is narrow and equivalent to "merge when pipeline succeeds" workflows.
- Requires `gitlab_labeler` to run before `gitlab_housekeeping` (already the case in production)
  - **Mitigation:** This is already the default pipeline ordering. If labels are missing, the MR is ineligible for optimistic merge and falls back to serial processing.

### Alternative 5: Reference-Graph Overlap Detection

Expand each MR's changed file paths using a reference graph built from the production bundle's datafiles. For each changed file, the expanded set includes: (1) the file itself, (2) forward refs (files referenced via `$ref` crossrefs), and (3) backward refs (files that reference the changed file). Two MRs overlap if their expanded path sets intersect.

The reference graph would be pre-computed during bundle validation and stored as a JSON artifact, loaded by `gitlab_housekeeping` at startup for O(1) dictionary lookups at merge time.

**Pros:**

- Finer-grained than label-based detection: same-service MRs with disjoint `$ref` neighborhoods can multi-merge
- Directly addresses the crossref examples (namespace+resource, role+user) at file level

**Cons:**

- **Fatal flaw:** the production bundle does not contain files introduced by MR branches. If MR-A adds a new user file with a `$ref` to an existing role, the reference graph built from master's bundle will not include that forward ref. The overlap check would miss it, undermining the safety guarantee.
- Fixing the flaw requires fetching each MR's branch content and rebuilding the graph per-MR, dramatically increasing complexity and API calls
- Requires building and maintaining a reference graph from the bundle (pre-computed artifact, versioned alongside the bundle)
- Reference expansion increases the overlap rate compared to label-based detection (more false positives from transitive refs)

**Assessment:** The fatal flaw makes this approach unsafe without per-MR graph rebuilding, which negates the simplicity advantage. The label-based approach (Alternative 4) provides comparable safety at much lower complexity. This alternative may be revisited if a mechanism for per-MR ref graph construction becomes available (e.g., via qontract-server branch-aware queries).

### Alternative 6: Change-Type Coverage Overlap

Use the existing change-type system to determine if two MRs overlap. Change types define schema + JSONPath boundaries for self-serviceable changes. If two MRs have no coverage overlap (i.e., they are covered by disjoint change-type definitions), they are safe to merge in parallel.

This was proposed by @maorfr: "if there is no coverage overlap between 2 MRs, they are safe to merge sequentially... it's not rock solid but it's likely a very good start." @
@fishi0x01 noted: "change types weren't designed with overlap in mind; two change types with different owners could still have overlapping refs." @maorfr's response: "if you find 2 MRs merged that shouldn't have, you create a change type that produces overlap."

**Pros:**

- Finer-grained than label-based detection: same-service MRs with disjoint change-type coverage can multi-merge
- Leverages existing change-type definitions and coverage logic
- Self-correcting: overlapping change types can be added reactively when problems are discovered

**Cons:**

- Change types were not designed for overlap detection; would need new logic to compare coverage between two MRs
- Requires qontract-server `/diff` endpoint in the merge loop context, which is not currently available to `gitlab_housekeeping`
- Change-type coverage operates at JSONPath level, not file level, introducing a conceptual mismatch with the file-based merge conflict model
- Adds dependency on qontract-server availability during the merge loop

**Assessment:** This is a promising future refinement (Phase 2) if label-based detection proves too coarse. It requires making change-type coverage information available to `gitlab_housekeeping` (e.g., via labels or notes). Should only be pursued if Phase 1 metrics show a high same-service overlap rate.

## Consequences

### Positive

- Throughput increase from ~8 MRs/hour (measured baseline) to ~10-20 MRs/hour for typical cross-service workloads (see throughput analysis below)
- Eliminates priority starvation: lower-priority MRs progress within the same loop iteration
- Label-based overlap detection is safe by construction: service-level isolation captures crossref dependencies without a reference graph
- Zero additional API calls for overlap detection (labels already present from `gitlab_labeler`)
- `tenant-*` label eligibility gate naturally limits blast radius: label-less MRs fall back to serial, multi-service MRs are serialized by overlap
- Per-repo `limit` semantics give operators fine-grained control over pipeline concurrency and queue behavior
- Phase 0 queue hardening (pipeline-history healthcheck, error flagging in merge queue) improves reliability regardless of multi-merge
- New metrics provide visibility into merge queue health and overlap rates
- No infrastructure changes, licensing costs, or CI migration
- ~50 lines of new Python -- minimal maintenance burden

### Negative

- Coarser than file-level detection: same-service MRs are serialized even if they touch different files
  - **Mitigation:** The `optimistic_merge_rejected_total` metric tracks overlap rate. If same-service overlap is consistently high, Phase 2 (change-type refinement) can unlock finer-grained detection.
- Residual risk of broken master for cross-service `$ref` dependencies not captured by label-based isolation
  - **Mitigation:** Cross-service `$ref`s are rare in app-interface. Post-merge master pipeline detects this immediately. This risk class is narrow and equivalent to "merge when pipeline succeeds" workflows.
- Requires `gitlab_labeler` to run before `gitlab_housekeeping`
  - **Mitigation:** This is already the production pipeline ordering. MRs without labels fall back to serial processing.
- If overlap rate exceeds 50% (many concurrent same-service MRs), the approach degrades toward serial behavior
  - **Mitigation:** The `optimistic_merge_rejected_total` metric tracks this. If overlap is consistently high, pursue Phase 2 (change-type refinement) or Alternative 2 (speculative train).

## Implementation Guidelines

### Phase 0: Queue Hardening and Config Tuning (immediate)

Operational improvements that reduce wasted CI and improve reliability, independent of multi-merge:

1. **Redefine `limit` as a per-repo cap, not per-run.** Currently `limit` controls how many MRs are rebased *per reconcile run*, with the counter resetting each invocation. Since `gitlab-housekeeping` runs frequently (~1 min cycles), a `limit: 2` still results in many MRs being rebased across runs, each triggering a pipeline -- most of which are wasted when only one MR merges per cycle. The fix: change the semantics so `limit` means "at most N MRs should be in a rebased-and-pipeline-pending state at any time for this repo." Before rebasing, count how many MRs already have running or recent pipelines and only rebase up to `limit - already_active`. Keep `limit` small (2-3) to minimize wasted CI. This is a prerequisite for Phase 1: with per-repo semantics, bumping `limit` to 6 for multi-merge becomes safe because it controls the *steady-state pipeline concurrency*, not the per-run rebase burst.

2. **Healthcheck-probe model for pipeline failures.** Simple pipeline-success filtering is dangerous because of flaky integrations -- transient CI errors would prematurely eject MRs from the queue. Instead, implement a retry budget using pipeline history: since we already fetch all pipelines for a given MR via `gl.get_merge_request_pipelines(mr)`, and every rebase creates a new pipeline, check the last N pipelines (configurable, default 3) for consecutive failures. If the last N pipelines all failed, apply a `merge-error` label and flag the MR in the existing merge queue rendering (markdown files / inscope plugins) so the IC can triage errors from the same merge queue page. No separate error queue or additional `State` persistence is needed. Auto-recover: when a new pipeline succeeds, the failure streak is broken and the `merge-error` label is removed. This balances retesting (crucial for flaky CI) with preventing zombie MRs from blocking the queue indefinitely.

3. **Flag MRs that fail to merge repeatedly.** When `mr.merge()` raises an exception (beyond `GitlabMRClosedError`), catch `GitlabOperationError` and apply a `merge-error` label to the MR. Exclude MRs with this label from the active merge queue. The `merge-error` label serves as a flag in the existing merge queue rendering (markdown files / inscope plugins) -- not a separate queue. The IC can filter for error-flagged MRs on the same merge queue page for triage. This handles corner cases like pipeline-pass-but-merge-fail (branch missing, approval retracted, GitLab transient errors).

4. **Broaden merge exception handling.** Currently only `GitlabMRClosedError` is caught. Add `GitlabOperationError` to handle fast-forward rejection, pipeline-gated rejection, branch-missing, and other server-side refusals gracefully. Note: python-gitlab does not have a `GitlabMergeError` class; `GitlabOperationError` is the common parent of all MR-related exceptions (`GitlabMRClosedError`, `GitlabMRForbiddenError`, `GitlabMROnBuildSuccessError`, etc.).

### Phase 1: Label-Based Optimistic Multi-Merge (1-2 weeks)

#### 1. Add `merge_limit` to the housekeeping schema in qontract-schemas

The schema must support an optional `merge_limit` field alongside the existing `limit`. `limit` controls the per-repo pipeline concurrency cap (how many MRs can be in a rebased-and-pipeline-pending state). `merge_limit` controls how many MRs can be merged per loop iteration (relevant for multi-merge). When absent, `merge_limit` defaults to `limit`.

#### 2. Implement label-based overlap detection

```python
TENANT_LABEL_PREFIX = "tenant-"

def get_tenant_labels(mr: ProjectMergeRequest) -> set[str]:
    """Extract tenant-* labels from an MR."""
    return {l for l in mr.labels if l.startswith(TENANT_LABEL_PREFIX)}

def is_eligible_for_optimistic_merge(mr: ProjectMergeRequest) -> bool:
    """MRs with at least one tenant-* label are eligible."""
    return bool(get_tenant_labels(mr))

def has_overlapping_labels(
    mr_labels: set[str], merged_labels: set[str]
) -> bool:
    """Two MRs overlap if they share any tenant-* label."""
    return bool(mr_labels & merged_labels)
```

This is the complete overlap detection implementation. No API calls, no bundle loading, no reference graph. Labels are already present on MRs from `gitlab_labeler`.

#### 3. Modify `merge_merge_requests()` merge loop

This is the most complex change. There are four interacting concerns:

**The `@retry` / `InsistOnPipelineError` interaction.** The current function is decorated with `@retry(max_attempts=10)`. When `insist=True` and a pipeline is still running, it raises `InsistOnPipelineError`, which restarts the entire function from the top. Any local state (`merged_labels`, `first_merge_done`) is lost on retry. The `insist` mechanism is effectively a polling loop that waits for the *first* rebased MR's pipeline to complete.

The solution: the `insist` wait-and-retry behavior only applies *before* the first merge. Once we have merged at least one MR, we stop waiting for running pipelines and only consider MRs whose pipelines have already completed successfully. This avoids the retry blowing away the multi-merge state, because we never raise `InsistOnPipelineError` after the first merge. Concretely, `wait_for_pipeline` with `insist` is only checked when `first_merge_done is False`.

**Fast-forward merge requires rebase.** App-interface uses fast-forward merge. After the first merge changes the target branch, subsequent MRs are no longer rebased and `mr.merge()` will be rejected. The solution: call `mr.rebase(skip_ci=True)` before `mr.merge()` for optimistic MRs. This rebases the MR onto the new target HEAD without triggering a new pipeline, allowing the fast-forward merge to proceed. The existing pipeline result is still valid because the MR's changes do not overlap with the merged changes (guaranteed by the label-based overlap check: different services = independent files).

**Merge rejection handling.** Even with `skip_ci` rebase, the merge may fail for other reasons (race conditions, GitLab transient errors). The python-gitlab library raises `GitlabOperationError` (or a subclass like `GitlabMRClosedError`, `GitlabMROnBuildSuccessError`) on rejection. The exception handler must catch `GitlabOperationError` broadly and treat rejection as a skip.

**Eligibility gate.** Only MRs with at least one `tenant-*` label are candidates for optimistic merge. MRs without `tenant-*` labels (global infrastructure changes, cross-cutting refactors) have no label to compare and fall back to serial processing. MRs touching many services (e.g. qr-bump) have many `tenant-*` labels and are naturally serialized by the overlap check.

```python
merged_labels: set[str] = set()
first_merge_done = False

for merge_request in merge_requests:
    mr = merge_request["mr"]

    if rebase:
        if first_merge_done:
            if not is_eligible_for_optimistic_merge(mr):
                continue
            mr_labels = get_tenant_labels(mr)
            if has_overlapping_labels(mr_labels, merged_labels):
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
                mr.rebase(skip_ci=True)

            mr.merge(squash=squash)
            merged_labels.update(get_tenant_labels(mr))
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
- `is_eligible_for_optimistic_merge()` gates which MRs can enter the optimistic path. MRs without `tenant-*` labels are silently skipped and deferred to the next serial cycle. MRs with many `tenant-*` labels are naturally serialized by the overlap check.
- No `paths_cache` or API calls needed for overlap detection -- labels are read directly from the MR object.

#### 4. Wire up per-repo `limit` and `merge_limit` in `run()`

```python
limit = hk.get("limit") or default_limit  # per-repo pipeline concurrency cap
merge_limit = hk.get("merge_limit") or limit  # max merges per loop iteration
```

In `rebase_merge_requests`, count MRs that already have running/recent pipelines and only rebase up to `limit - already_active`.

#### 5. Add Prometheus metrics

- `optimistic_merges_total` (Counter, labels: `project_id`) -- MRs merged via the optimistic non-overlapping path
- `optimistic_merge_rejected_total` (Counter, labels: `project_id`, `reason`) -- MRs skipped due to label overlap, ineligibility, or GitLab merge rejection
- `merge_batch_size` (Histogram, labels: `project_id`) -- number of MRs merged per loop iteration

### Throughput Analysis

**Measured baseline:** During ADR development, a full production pod log (`gitlab-housekeeping-4-68bff97fd6-dzls2-int`, 2026-03-03 14:28–21:21 UTC, 9,326 lines) was captured and analyzed. Key findings from the observation window:

- **53 app-interface merges** over 6h 40m → **~7.9 MRs/hour sustained throughput**
- **Median inter-merge interval: ~7.7 minutes** (range: 4m–17m, remarkably consistent across the full window)
- **Reconcile loop cadence: ~1.5–2 minutes** per cycle
- **2,142 "rebase limit reached" events** — massive rebase churn; with `limit: 2`, only 2 MRs are rebased per run but across ~30 runs/hour, many MRs get repeatedly rebased and invalidated
- **267 "unable to merge" errors** — unhandled edge cases (405 Method Not Allowed, branch state issues) that block queue slots
- **MR starvation case (MR 177008):** appeared 12+ times as "rebase limit reached" over 3h 51m, never merged during the entire 6h 52m observation window despite having an `lgtm` label — while 53 other MRs merged ahead of it

The theoretical calculation (pipeline ~8 min + insist ~1 min + reconcile ~1 min = ~10 min/cycle → ~6 MRs/hour) slightly underestimates the empirical rate because the insist polling and reconcile overhead vary. The measured ~7.9 MRs/hour represents peak serial throughput under sustained load with a non-empty queue. Note: recent pipeline optimizations (skipping template-render for most MRs) may further improve this baseline.

**With label-based optimistic multi-merge:** The first merge still takes ~10 min (waiting for pipeline via insist). After the first merge, additional MRs whose pipelines have already completed and whose `tenant-*` labels don't overlap with merged MRs can merge after a `skip_ci` rebase (seconds per merge). Since all rebased MRs start pipelines at roughly the same time, most finish within a narrow window around the 8-minute mark.

With a per-repo `limit: 6` (meaning 6 MRs in a rebased-and-pipeline-pending state at any time) and label-based overlap detection, the effective non-overlapping rate depends on the MR mix. Label-based overlap is coarser than file-level -- all MRs touching the same service are treated as overlapping, even if they modify different files. The throughput gain is concentrated in cross-service workloads.

**Assumptions:**

- 50-70% of queued MRs touch different services (non-overlapping `tenant-*` labels). This is lower than the ~80% raw file-level estimate because same-service MRs are serialized regardless of which files they touch.
- Only MRs with `tenant-*` labels are eligible; MRs without labels (global infrastructure) fall back to serial. MRs touching many services are naturally serialized by overlap check.
- Pipeline time variance: 6-10 minutes, with most completing within 1-2 minutes of each other
- `skip_ci` rebase takes ~2-5 seconds per MR (GitLab API call, no pipeline trigger)
- Jenkins has sufficient executor capacity for 6 parallel pipelines (spot autoscaling)

**Projections:**

- **Conservative estimate:** 1 (first) + 1 (optimistic) = 2 merges per 10-min cycle = **~12 MRs/hour**
- **Optimistic estimate:** 1 + 3 = 4 per cycle = **~24 MRs/hour**
- **Realistic midpoint:** ~10-20 MRs/hour, depending on service distribution of queued MRs, pipeline time variance, and `skip_ci` rebase reliability

Even the conservative estimate represents a ~1.5x improvement over the measured ~8 MRs/hour baseline. The realistic midpoint of ~15 MRs/hour would nearly double throughput. Phase 2 (change-type refinement) could unlock further gains by allowing same-service MRs to multi-merge.

### Phase 2: Change-Type Refinement (conditional)

Only pursue if Phase 1 metrics show a high same-service overlap rate (i.e., many MRs blocked because they share `tenant-*` labels even though their actual changes are independent). This phase uses change-type coverage to unlock finer-grained multi-merge for same-service MRs.

**Prerequisite:** Phase 1 `optimistic_merge_rejected_total{reason="overlap"}` metric shows that >30% of candidate MRs are being serialized due to same-service label overlap.

**Approach:** Use the existing change-type system to determine if two same-service MRs have disjoint coverage. If their change-type definitions do not overlap, the MRs are safe to merge in parallel even though they touch the same service directory.

**Implementation considerations:**

- Change-type coverage is currently computed during CI via the qontract-server `/diff` endpoint, which is not available in the `gitlab_housekeeping` merge loop context
- Options for making coverage available: (a) store coverage results as MR labels or notes during CI, (b) query a cached `/diff` result, or (c) implement a lightweight coverage check in `gitlab_housekeeping` using the change-type definitions directly
- Change types were not designed for overlap detection; new logic would be needed to compare coverage boundaries between two MRs
- Self-correcting: if two MRs with disjoint change-type coverage turn out to conflict, a new change type can be created that produces overlap between them

Defer detailed design until Phase 1 data is available.

### Checklist

**Phase 0:**

- [ ] Redefine `limit` as per-repo cap (count already-active pipelines before rebasing)
- [ ] Implement healthcheck-probe model for pipeline failures (check last N pipelines from `gl.get_merge_request_pipelines(mr)`, `merge-error` label after N consecutive failures)
- [ ] Broaden merge exception handling to catch `GitlabOperationError`
- [ ] Add `merge-error` flag in existing merge queue rendering for MRs that fail to merge repeatedly (corner cases: pipeline-pass-but-merge-fail)

**Phase 1:**

- [ ] Add `merge_limit` to housekeeping schema in qontract-schemas
- [ ] Implement `get_tenant_labels()`, `is_eligible_for_optimistic_merge()`, and `has_overlapping_labels()`
- [ ] Replace the single-merge `return` with label-based multi-merge loop
- [ ] Add `tenant-*` label eligibility gate (MRs without labels fall back to serial)
- [ ] Add `mr.rebase(skip_ci=True)` for optimistic MRs before merge
- [ ] Verify `skip_ci` parameter support in python-gitlab `mr.rebase()`
- [ ] Wire up per-repo `limit` and `merge_limit` in `run()` (backward compatible)
- [ ] Add `optimistic_merges_total`, `optimistic_merge_rejected_total`, `merge_batch_size` metrics
- [ ] Add unit tests for label overlap detection and multi-merge behavior
- [ ] Set `limit: 6` (per-repo cap) in app-interface `app.yml` once per-repo semantics are in place
- [ ] Monitor `optimistic_merge_rejected_total` for overlap rate after rollout

**Phase 2 (conditional):**

- [ ] Evaluate Phase 1 overlap metrics -- only proceed if same-service overlap rate >30%
- [ ] Design change-type coverage comparison for same-service MRs
- [ ] Make change-type coverage available to `gitlab_housekeeping` (via labels or notes)

## References

- Implementation: `reconcile/gitlab_housekeeping.py` -- merge loop, rebase logic, priority sorting
- Implementation: `reconcile/gitlab_labeler.py` -- `tenant-*` label assignment based on changed paths
- Implementation: `reconcile/utils/gitlab_api.py` -- `get_merge_request_changed_paths()` (used by `gitlab_labeler`, available for future refinements)
- Implementation: `reconcile/utils/state.py` -- `State` (no longer needed for healthcheck-probe; pipeline history from `gl.get_merge_request_pipelines(mr)` is used instead)
- Implementation: `reconcile/change_owners/` -- change-type coverage logic (Phase 2 reference)
- Crossrefs: `qontract-schemas/schemas/common-1.json` -- `$ref` crossref definition
- App-interface config: `data/services/app-interface/app.yml` -- `gitlabHousekeeping.limit`
- CI pipeline: `hack/pr_check.sh`, `hack/manual_reconcile.sh`, `hack/select-integrations.py`
- External: [GitLab merge trains](https://docs.gitlab.com/ci/pipelines/merge_trains/)
- External: [python-gitlab MR rebase](https://python-gitlab.readthedocs.io/en/stable/gl_objects/merge_requests.html) -- `mr.rebase(skip_ci=True)`
