# Integration gitlab-housekeeping

`gitlab-housekeeping` manages the merge queue for app-interface GitLab repositories. It handles stale issue/MR lifecycle, error-label healthchecks, serial merging with pipeline and rebase gates, rebase concurrency capping, and optimistic multi-merge (OMM) for non-overlapping tenant-scoped MRs.


## Module structure

* `reconcile.gitlab_housekeeping.labels` contains label constants (`MERGE_LABELS_PRIORITY`, `HOLD_LABELS`, `ERROR_LABELS`, `TENANT_LABEL_PREFIX`) and predicates that classify MRs by their labels (`is_good_to_merge`, `get_tenant_labels`, `is_eligible_for_optimistic_merge`, `has_overlapping_labels`). Also imported by the `gitlab_labeler` integration.
* `reconcile.gitlab_housekeeping.helpers` holds all Prometheus metric objects (counters, gauges, histograms), pipeline utilities (`get_timed_out_pipelines`, `clean_pipelines`, `is_rebased`), and `calculate_time_since_approval`.
* `reconcile.gitlab_housekeeping.queue` preprocesses open MRs into a priority-sorted merge queue (`get_merge_requests`, `preprocess_merge_requests`) and verifies on-demand test results.
* `reconcile.gitlab_housekeeping.healthcheck` manages error labels on queue-eligible MRs: applies or removes `rebase-error`, `pipeline-error`, and `merge-error` based on merge status, consecutive pipeline failures, and post-label note activity.
* `reconcile.gitlab_housekeeping.rebase` implements rebase strategies (`RebaseStrategy` enum, active-cap dispatcher) and the per-MR rebase attempt logic.
* `reconcile.gitlab_housekeeping.omm` owns the optimistic multi-merge group steps: group formation from non-overlapping tenant-labeled MRs, per-member processing (merge, eject, skip-ci rebase), group expansion with new candidates, and cleanup.
* `reconcile.gitlab_housekeeping.gitlab_housekeeping` is the coordinator and integration entry point. It contains `run()`, the serial merge loop, stale-item handling, token expiration metrics, and retry infrastructure (`ReloadToggle`, `InsistOnPipelineError`). It imports all other modules and decides when the group steps run; it is never imported by them.
