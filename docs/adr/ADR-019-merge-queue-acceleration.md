# ADR-019: Merge Queue Acceleration via Optimistic Non-Overlapping Multi-Merge

**Status:** Proposed
**Date:** 2026-03-03
**Authors:** @TGPSKI

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

**Implement optimistic non-overlapping multi-merge in `gitlab_housekeeping.py`: after the first merge in a loop, merge subsequent MRs without re-rebase if their changed files do not overlap with any already-merged MR's changed files.**

### Key Points

- The first MR in each loop iteration still requires `is_rebased()` and a passing pipeline (unchanged safety)
- Subsequent MRs skip the `is_rebased()` check if their changed file paths have zero intersection with the union of all previously merged MRs' changed file paths
- The `if rebase: return` exit after a single merge is removed, allowing multiple merges per loop
- `rebase_limit` is separated from `merge_limit` so more MRs can be kept pipeline-ready simultaneously
- A circuit breaker prevents zombie MRs (repeated pipeline failures) from blocking the queue
- New Prometheus metrics track optimistic merge success rate and overlap frequency

### Rationale

Most app-interface MRs modify independent YAML datafiles under different service directories. When MR-A changes `data/services/foo/app.yml` and MR-B changes `data/services/bar/deploy.yml`, MR-B's pipeline result against `old_master` is identical to its result against `old_master + MR-A`. The file contents, schema validation, and integration dry-runs are all independent.

This approach gets 70-80% of the throughput benefit of GitLab merge trains with no infrastructure changes and ~100 lines of code.

### Relationship to Existing Changed-Path Analysis

Several integrations already analyze which files an MR changes. This ADR's overlap detection reuses an existing utility rather than introducing a new mechanism:

- **`GitLabApi.get_merge_request_changed_paths()`** (`reconcile/utils/gitlab_api.py:405`) is the shared method that calls the GitLab MR changes API. It is already used by `gitlab_owners` (for CODEOWNERS-style approval routing), `gitlab_labeler` (for `tenant-*` label assignment), and `openshift_saas_deploy_change_tester` (for filtering saas-file diffs). This ADR's overlap detection reuses the same method.

- **`gitlab_labeler`** already applies `tenant-*` labels (e.g. `tenant-foo`) based on which `data/services/` directories an MR touches. These labels are present on the MR by the time `gitlab_housekeeping` runs. A coarse overlap check could compare `tenant-*` labels between MRs with zero additional API calls. However, tenant labels are too imprecise: two MRs touching different files under the same service directory (e.g. `app.yml` vs `deploy.yml`) would incorrectly appear to overlap.

- **change-owners** uses a different mechanism entirely: the qontract-server `/diff` endpoint compares two bundle SHAs. This provides deep semantic diff information (per-field changes, change-type coverage), but requires a running qontract-server with loaded bundles and is not available in the housekeeping merge loop context.

The decision is to use `get_merge_request_changed_paths()` directly for exact file-level overlap detection. This adds one GitLab API call per MR candidate in the merge loop (at most `merge_limit` calls, typically 6). If API call volume becomes a concern, a two-tier approach could first check `tenant-*` labels (zero API calls, coarse filter) and only call the API for MRs with overlapping tenant labels.

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

### Alternative 3: Optimistic Non-Overlapping Multi-Merge (Selected)

After the first merge, allow subsequent non-overlapping MRs to merge without re-rebase.

**Pros:**

- No infrastructure changes (keeps Jenkins, no licensing changes)
- Minimal code changes (~100 lines in `gitlab_housekeeping.py`)
- Uses existing `GitLabApi.get_merge_request_changed_paths()` API
- Safe fallback: overlapping MRs are deferred to re-rebase (no regression)
- Projected 15-30 MRs/hour for typical non-overlapping workloads
- 1-2 week implementation timeline
- New metrics provide data to justify further investment if needed

**Cons:**

- Overlapping MRs fall back to serial behavior
  - **Mitigation:** Most app-interface MRs are non-overlapping; the `optimistic_merge_rejected_total` metric quantifies overlap rate
- Theoretical risk of broken master when non-overlapping MRs have semantic dependencies (e.g. schema change + new datafile using that schema)
  - **Mitigation:** This is rare in app-interface. The post-merge master pipeline catches it immediately. This is the same risk model as "merge when pipeline succeeds" workflows.

## Consequences

### Positive

- Throughput increase from ~7 MRs/hour to ~15-30 MRs/hour for typical workloads (see throughput analysis below)
- Eliminates priority starvation: lower-priority MRs progress within the same loop iteration
- Separated `rebase_limit` / `merge_limit` gives operators fine-grained control over queue behavior
- Circuit breaker prevents zombie MRs from blocking the queue
- New metrics provide visibility into merge queue health and overlap rates
- No infrastructure changes, licensing costs, or CI migration

### Negative

- Optimistic merges introduce a small risk of broken master for semantically dependent but file-disjoint changes
  - **Mitigation:** Post-merge master pipeline detects this. The risk is equivalent to any "merge when pipeline succeeds" workflow and is very low for app-interface's YAML-file-per-service structure.
- Additional GitLab API calls per MR (`get_merge_request_changed_paths`) in the merge loop
  - **Mitigation:** One API call per MR candidate. With `merge_limit: 6`, this is at most 6 additional calls per loop.
- If overlap rate exceeds 30%, the approach degrades toward serial behavior
  - **Mitigation:** The `optimistic_merge_rejected_total` metric tracks this. If overlap rate is high, escalate to Alternative 2 (speculative train).

## Implementation Guidelines

### Phase 0: Config Bump (immediate)

Increase `limit` from 2 to 6 in app-interface `app.yml`. While this alone doesn't break the serial dependency, it keeps more MRs rebased in the queue, reducing wait time for the first merge each loop. This is a prerequisite for Phase 1 to have enough pipeline-ready MRs to merge in batch.

### Phase 1: Optimistic Multi-Merge (1-2 weeks)

#### 1. Add `rebase_limit` to the housekeeping schema in qontract-schemas

The schema must support an optional `rebase_limit` field alongside the existing `limit`. When absent, `rebase_limit` defaults to `limit`.

#### 2. Implement overlap detection helper

```python
def get_changed_paths(mr: ProjectMergeRequest, gl: GitLabApi) -> set[str]:
    return set(gl.get_merge_request_changed_paths(mr))

def has_overlapping_changes(
    mr_paths: set[str], merged_paths: set[str]
) -> bool:
    return bool(mr_paths & merged_paths)
```

#### 3. Modify `merge_merge_requests()` merge loop

This is the most complex change. There are three interacting concerns:

**The `@retry` / `InsistOnPipelineError` interaction.** The current function is decorated with `@retry(max_attempts=10)`. When `insist=True` and a pipeline is still running, it raises `InsistOnPipelineError`, which restarts the entire function from the top. Any local state (`merged_paths`, `first_merge_done`) is lost on retry. The `insist` mechanism is effectively a polling loop that waits for the *first* rebased MR's pipeline to complete.

The solution: the `insist` wait-and-retry behavior only applies *before* the first merge. Once we have merged at least one MR, we stop waiting for running pipelines and only consider MRs whose pipelines have already completed successfully. This avoids the retry blowing away the multi-merge state, because we never raise `InsistOnPipelineError` after the first merge. Concretely, `wait_for_pipeline` with `insist` is only checked when `first_merge_done is False`.

**Merge rejection on non-rebased MRs.** After the first merge changes the target branch, subsequent MRs are no longer rebased. Calling `mr.merge()` on a non-rebased MR may succeed (merge commit projects) or fail (fast-forward projects). The python-gitlab library raises `GitlabMergeError` (or a subclass) on rejection. The exception handler must catch broadly -- not just `GitlabMRClosedError` but any `GitlabMergeError` -- and treat rejection as a skip (the MR will be re-rebased next loop).

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
                paths_cache[mr.iid] = get_changed_paths(mr, gl)
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
            mr.merge(squash=squash)
            if mr.iid not in paths_cache:
                paths_cache[mr.iid] = get_changed_paths(mr, gl)
            merged_paths.update(paths_cache[mr.iid])
            if first_merge_done:
                optimistic_merges.labels(mr.target_project_id).inc()
            first_merge_done = True
            merges += 1
            # ... existing metrics (merged_merge_requests, time_to_merge) ...
        except gitlab.exceptions.GitlabMRClosedError as e:
            logging.error(f"unable to merge {mr.iid}: {e}")
        except gitlab.exceptions.GitlabMergeError as e:
            # GitLab rejected the merge (e.g. fast-forward not possible
            # because MR is not rebased onto current target). Skip this MR;
            # it will be re-rebased next loop.
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
- The `insist=False` fallback call (lines 739-753 in `run()`) works correctly: it never raises `InsistOnPipelineError` regardless, so the multi-merge loop runs without interruption.
- `GitlabMergeError` is the base class for merge-related failures in python-gitlab. Catching it covers fast-forward rejection, pipeline-gated rejection, and other server-side refusals.
- `paths_cache` avoids calling `get_merge_request_changed_paths()` twice for the same MR (once for the overlap check, once for updating `merged_paths` after merge).

#### 4. Separate `rebase_limit` from `merge_limit` in `run()`

```python
merge_limit = hk.get("limit") or default_limit
rebase_limit = hk.get("rebase_limit") or merge_limit
```

#### 5. Add circuit breaker for zombie MRs

Track consecutive pipeline failures per MR IID in `State`. After 3 consecutive failures, skip the MR for the current loop and log a warning. Reset the counter when the MR's pipeline succeeds or a new commit is pushed.

#### 6. Add Prometheus metrics

- `optimistic_merges_total` (Counter, labels: `project_id`) -- MRs merged via the optimistic non-overlapping path
- `optimistic_merge_rejected_total` (Counter, labels: `project_id`, `reason`) -- MRs skipped due to file overlap or GitLab merge rejection
- `merge_batch_size` (Histogram, labels: `project_id`) -- number of MRs merged per loop iteration

### Throughput Analysis

**Current state:** 1 merge per cycle. Cycle time = pipeline duration (~8 min) + insist retry overhead (~1 min) + reconcile sleep (~1 min) = ~10 min. Throughput: ~6 MRs/hour.

**With optimistic multi-merge:** The first merge still takes ~10 min (waiting for pipeline via insist). After the first merge, additional MRs whose pipelines have already completed can merge immediately (seconds per merge). Since all rebased MRs start pipelines at roughly the same time, most finish within a narrow window around the 8-minute mark.

With `rebase_limit: 10` and an 80% non-overlapping rate (typical for app-interface), expect ~8 MRs eligible for optimistic merge per cycle. Not all will have completed pipelines -- pipeline times vary and some may still be running when the first MR merges. Conservatively assume 3-5 optimistic merges succeed per cycle.

- **Conservative estimate:** 1 (first) + 3 (optimistic) = 4 merges per 10-min cycle = **~24 MRs/hour**
- **Optimistic estimate:** 1 + 5 = 6 per cycle = **~36 MRs/hour**
- **Realistic midpoint:** ~15-30 MRs/hour, depending on pipeline time variance and overlap rate

These projections assume Jenkins has sufficient executor capacity for 10 parallel pipelines. Jenkins spot autoscaling already handles this.

### Phase 2: Speculative Stacking (conditional)

Only pursue if Phase 1 metrics show overlap rate exceeding 30%. This phase involves temporary branch creation, Jenkins job parameterization, and cascade invalidation logic. Defer design until Phase 1 data is available.

### Checklist

- [ ] Add `rebase_limit` to housekeeping schema in qontract-schemas
- [ ] Implement `get_changed_paths()` and `has_overlapping_changes()` in `gitlab_housekeeping.py`
- [ ] Replace the single-merge `return` with overlap-aware multi-merge loop
- [ ] Separate `rebase_limit` from `merge_limit` in `run()` (backward compatible)
- [ ] Add circuit breaker with `State` tracking
- [ ] Add `optimistic_merges_total`, `optimistic_merge_rejected_total`, `merge_batch_size` metrics
- [ ] Add unit tests for overlap detection and multi-merge behavior
- [ ] Set `limit: 6`, `rebase_limit: 10` in app-interface `app.yml`
- [ ] Monitor `optimistic_merge_rejected_total` for overlap rate after rollout

## References

- Implementation: `reconcile/gitlab_housekeeping.py` -- merge loop, rebase logic, priority sorting
- Implementation: `reconcile/utils/gitlab_api.py:405` -- `get_merge_request_changed_paths()`
- Implementation: `reconcile/utils/state.py` -- `State` for circuit breaker persistence
- App-interface config: `data/services/app-interface/app.yml` -- `gitlabHousekeeping.limit`
- CI pipeline: `hack/pr_check.sh`, `hack/manual_reconcile.sh`, `hack/select-integrations.py`
- External: [GitLab merge trains](https://docs.gitlab.com/ci/pipelines/merge_trains/)
- External: [GitLab merge_ref API](https://docs.gitlab.com/api/merge_requests/#merge-to-default-merge-ref-path)
