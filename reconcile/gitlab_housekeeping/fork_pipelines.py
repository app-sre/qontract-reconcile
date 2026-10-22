from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import gitlab
from prometheus_client import Counter

if TYPE_CHECKING:
    from gitlab.v4.objects import (
        ProjectMergeRequest,
        ProjectMergeRequestPipeline,
    )

    from reconcile.utils.gitlab_api import GitLabApi
    from reconcile.utils.state import State

triggered_fork_pipelines = Counter(
    name="qontract_reconcile_gitlab_housekeeping_fork_pipelines_triggered",
    documentation=(
        "Number of merge-request pipelines triggered to run in the parent "
        "project's context for merge requests opened from a fork"
    ),
    labelnames=["project_id"],
)

NO_CI_CONFIG_STATE_VALUE = "missing-gitlab-ci-yml"


def trigger_fork_pipelines(
    dry_run: bool,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    state: State,
    *,
    pipeline_cache: dict[int, list[ProjectMergeRequestPipeline]],
) -> None:
    """Trigger a pipeline, running in this (the parent) project's context,
    for every open fork MR whose current HEAD commit doesn't have one yet.

    By default GitLab only runs a fork MR's pipeline in the fork itself,
    using the fork's own (usually absent) runners/variables. Getting it to
    run against the parent project's runners normally requires a maintainer
    to manually accept a "this may be malicious" warning for every single
    fork MR. On a private, SSO-gated GitLab instance where every fork is
    created by an authenticated internal user, that per-MR human gate adds
    friction without a corresponding security benefit, so this triggers it
    automatically instead -- gated behind the `trigger_fork_pipelines`
    per-repo housekeeping config flag (default off), so it has to be
    deliberately opted into per project.

    Idempotent per (mr, sha): a successful trigger is remembered via
    GitLab's own pipeline list (checked fresh via get_merge_request_pipelines
    every run, not via the in-process pipeline_cache, which doesn't survive
    between reconcile loop iterations). A *failed* trigger -- most
    commonly a fork branch with no .gitlab-ci.yml at all, which GitLab
    reports as a GitlabCreateError ("Missing .gitlab-ci.yml file") rather
    than a silent no-op -- leaves nothing on GitLab's side to detect, so
    that outcome is instead remembered in `state` (this integration's
    S3-backed per-run state store) keyed by (mr, sha), the same pattern
    queue.py's verify_on_demand_tests() already uses. Without this, a fork
    MR with no CI config would retry the same doomed API call on every
    single loop iteration for as long as it stays open -- this integration
    runs with no sleep interval in production (sharded, back-to-back), so
    that's unbounded wasted traffic against the bot's API rate-limit
    budget, not a one-off cost. The state key is scoped to the exact sha,
    so a new commit on the MR is always retried fresh.
    """
    for mr in project_merge_requests:
        if mr.source_project_id == gl.project.id:
            continue  # not a fork MR, nothing to do

        state_key = f"{gl.project.path_with_namespace}/{mr.iid}/{mr.sha}"
        if state.get(state_key, None) == NO_CI_CONFIG_STATE_VALUE:
            continue  # already tried and failed for this exact commit

        if mr.iid in pipeline_cache:
            pipelines = pipeline_cache[mr.iid]
        else:
            pipelines = gl.get_merge_request_pipelines(mr)
            pipeline_cache[mr.iid] = pipelines

        if any(p.sha == mr.sha for p in pipelines):
            continue  # already has a pipeline for the current head commit

        logging.info([
            "trigger_fork_pipeline",
            gl.project.name,
            mr.iid,
            mr.sha,
        ])
        if dry_run:
            continue

        try:
            gl.create_merge_request_pipeline(mr)
        except gitlab.exceptions.GitlabCreateError as e:
            # Most commonly "Missing .gitlab-ci.yml file": the fork branch
            # simply has no CI config at this commit, which is the normal
            # case for the vast majority of MRs until GitLab CI adoption
            # grows -- not a real error, and not a reason to stop processing
            # the rest of this project's MRs. Remember it so we don't retry
            # the same doomed call again next loop iteration.
            logging.info([
                "trigger_fork_pipeline",
                "skipped",
                gl.project.name,
                mr.iid,
                str(e),
            ])
            state.add(state_key, NO_CI_CONFIG_STATE_VALUE, force=True)
            continue

        triggered_fork_pipelines.labels(project_id=gl.project.id).inc()
        # the pipeline we just created isn't reflected in the cached list;
        # drop it so a later lookup this same run re-fetches and sees it
        pipeline_cache.pop(mr.iid, None)
