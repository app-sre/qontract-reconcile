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
STATE_KEY_PREFIX = "gitlab-housekeeping-fork-pipeline"
# GitLab's exact, documented response for a ref with no CI config at all:
# https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/
MISSING_CI_CONFIG_RESPONSE_CODE = 400
MISSING_CI_CONFIG_MESSAGE = "Missing .gitlab-ci.yml file"


def _is_missing_ci_config_error(e: gitlab.exceptions.GitlabCreateError) -> bool:
    return (
        e.response_code == MISSING_CI_CONFIG_RESPONSE_CODE
        and (e.error_message or "").strip() == MISSING_CI_CONFIG_MESSAGE
    )


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
    to manually accept a warning that this executes fork-controlled CI
    configuration with the parent project's runners, variables, and the
    triggering member's permissions -- GitLab's own docs warn this can be
    used to steal secrets before merge. This triggers it automatically
    instead, which is a deliberate trust decision for this specific
    instance (private, SSO-gated, every fork created by an authenticated
    internal user) rather than a claim that the risk doesn't apply -- gated
    behind the `trigger_fork_pipelines` per-repo housekeeping config flag
    (default off), so it has to be deliberately opted into per project with
    that trade-off understood.

    Idempotent per (mr, sha): a successful trigger is remembered via
    GitLab's own pipeline list (checked fresh via get_merge_request_pipelines
    every run, not via the in-process pipeline_cache, which doesn't survive
    between reconcile loop iterations). A fork branch with no .gitlab-ci.yml
    at all -- the normal case for the vast majority of MRs until GitLab CI
    adoption grows -- leaves nothing on GitLab's side to detect (GitLab
    responds with a 400 GitlabCreateError whose message is exactly "Missing
    .gitlab-ci.yml file", rather than a silent no-op), so that specific,
    positively-identified response (matched on both status code and exact
    message via _is_missing_ci_config_error -- not a loose substring match,
    since an unrelated error could coincidentally mention the filename too)
    is remembered in `state` (this integration's S3-backed per-run state
    store), keyed by (mr, sha) under a key prefix distinct from queue.py's
    verify_on_demand_tests() (which uses the same {project}/{iid}/{sha}
    shape for a different purpose -- an unprefixed key here would collide
    and corrupt both features' state on repos that enable both). Without
    this, a fork MR with no CI config would retry the same doomed API call
    on every single loop iteration for as long as it stays open -- this
    integration runs with no sleep interval in production (sharded,
    back-to-back), so that's unbounded wasted traffic against the bot's
    API rate-limit budget, not a one-off cost. Any other creation failure,
    and any failure just listing the MR's existing pipelines, is logged
    but not cached and does not stop the rest of this project's MRs from
    being processed -- it's simply retried next run. The state key is
    scoped to the exact sha, so a new commit on the MR is always retried
    fresh.
    """
    for mr in project_merge_requests:
        if mr.source_project_id == gl.project.id:
            continue  # not a fork MR, nothing to do

        state_key = (
            f"{STATE_KEY_PREFIX}/{gl.project.path_with_namespace}/{mr.iid}/{mr.sha}"
        )
        if state.get(state_key, None) == NO_CI_CONFIG_STATE_VALUE:
            continue  # already tried and failed for this exact commit

        if mr.iid in pipeline_cache:
            pipelines = pipeline_cache[mr.iid]
        else:
            try:
                pipelines = gl.get_merge_request_pipelines(mr)
            except gitlab.exceptions.GitlabListError as e:
                # A lookup failure here is unrelated to whether this MR has
                # CI config -- don't cache anything, just skip this MR for
                # this loop iteration and keep processing the rest.
                logging.warning([
                    "trigger_fork_pipeline",
                    "pipeline_lookup_failed",
                    gl.project.name,
                    mr.iid,
                    str(e),
                ])
                continue
            pipeline_cache[mr.iid] = pipelines

        # get_merge_request_pipelines lists every pipeline tied to the MR
        # regardless of which project ran it -- a fork with its own CI/
        # runner can have its own pipeline for this exact sha, which must
        # not be mistaken for the parent-context run we actually want.
        if any(p.sha == mr.sha and p.project_id == gl.project.id for p in pipelines):
            continue  # already has a parent-context pipeline for this commit

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
            if _is_missing_ci_config_error(e):
                # "Missing .gitlab-ci.yml file": the fork branch simply has
                # no CI config at this commit, which is the normal case for
                # the vast majority of MRs until GitLab CI adoption grows --
                # not a real error, and not a reason to stop processing the
                # rest of this project's MRs. This specific, positively
                # identified outcome is remembered so it isn't retried
                # every loop iteration; any other creation failure (a
                # transient error, a permissions issue, etc.) is logged and
                # left to retry next run rather than cached as permanent,
                # since it may well resolve on its own.
                logging.info([
                    "trigger_fork_pipeline",
                    "skipped",
                    gl.project.name,
                    mr.iid,
                    str(e),
                ])
                state.add(state_key, NO_CI_CONFIG_STATE_VALUE, force=True)
            else:
                logging.warning([
                    "trigger_fork_pipeline",
                    "failed",
                    gl.project.name,
                    mr.iid,
                    str(e),
                ])
            continue

        triggered_fork_pipelines.labels(project_id=gl.project.id).inc()
        # the pipeline we just created isn't reflected in the cached list;
        # drop it so a later lookup this same run re-fetches and sees it
        pipeline_cache.pop(mr.iid, None)
