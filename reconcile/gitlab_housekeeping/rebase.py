from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

import gitlab
from gitlab.const import PipelineStatus

from reconcile.gitlab_housekeeping.helpers import (
    _cancel_timed_out_pipelines,
    _should_skip_for_running_pipeline,
    is_rebased,
    rebased_merge_requests,
)
from reconcile.gitlab_housekeeping.queue import get_merge_requests
from reconcile.utils.mr.labels import OMM_PENDING
from reconcile.utils.unleash import get_feature_variant

if TYPE_CHECKING:
    from collections.abc import Iterable

    from gitlab.v4.objects import (
        ProjectMergeRequest,
    )

    from reconcile.utils.gitlab_api import GitLabApi
    from reconcile.utils.state import State


class RebaseStrategy(StrEnum):
    ACTIVE_CAP = "active-cap"
    ACTIVE_CAP_MULTI_MERGE = "active-cap-multi-merge"


REBASE_STRATEGY_TOGGLE = "gitlab-housekeeping-rebase-strategy"
DEFAULT_REBASE_STRATEGY = RebaseStrategy.ACTIVE_CAP


def get_rebase_strategy() -> RebaseStrategy:
    """Resolve the rebase strategy from an Unleash feature variant."""
    value = get_feature_variant(
        REBASE_STRATEGY_TOGGLE, default_variant=DEFAULT_REBASE_STRATEGY.value
    )
    try:
        return RebaseStrategy(value)
    except ValueError:
        logging.warning(
            f"Unknown rebase strategy variant '{value}', "
            f"falling back to {DEFAULT_REBASE_STRATEGY.value}"
        )
        return DEFAULT_REBASE_STRATEGY


def _try_rebase(
    dry_run: bool,
    gl: GitLabApi,
    mr: ProjectMergeRequest,
) -> bool:
    """Attempt to rebase a MR. Returns True on success, False on failure."""
    try:
        logging.info(["rebase", gl.project.name, mr.iid])
        if not dry_run:
            mr.rebase()
            rebased_merge_requests.labels(mr.target_project_id).inc()
        return True
    except gitlab.exceptions.GitlabMRRebaseError as e:
        logging.error(f"unable to rebase {mr.iid}: {e}")
        return False


def rebase_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    rebase_limit: int,
    state: State,
    pipeline_timeout: int | None = None,
    wait_for_pipeline: bool = False,
    users_allowed_to_label: Iterable[str] | None = None,
    strategy: RebaseStrategy = DEFAULT_REBASE_STRATEGY,
) -> None:
    dispatch = {
        RebaseStrategy.ACTIVE_CAP: _rebase_merge_requests_active_cap,
        RebaseStrategy.ACTIVE_CAP_MULTI_MERGE: _rebase_merge_requests_active_cap,
    }

    fn = dispatch[strategy]
    fn(
        dry_run=dry_run,
        gl=gl,
        rebase_limit=rebase_limit,
        state=state,
        pipeline_timeout=pipeline_timeout,
        wait_for_pipeline=wait_for_pipeline,
        users_allowed_to_label=users_allowed_to_label,
    )


def _rebase_merge_requests_active_cap(
    dry_run: bool,
    gl: GitLabApi,
    rebase_limit: int,
    state: State,
    pipeline_timeout: int | None = None,
    wait_for_pipeline: bool = False,
    users_allowed_to_label: Iterable[str] | None = None,
) -> None:
    """Active-cap strategy: scan the full queue, count MRs with active
    pipelines, and only rebase up to (rebase_limit - already_active)
    additional MRs.  This treats rebase_limit as a per-repo concurrency cap
    on in-flight pipelines rather than a visibility window."""
    merge_requests = [
        item["mr"]
        for item in get_merge_requests(
            dry_run=dry_run,
            gl=gl,
            state=state,
            users_allowed_to_label=users_allowed_to_label,
            skip_unmergeable=False,
        )
        if not item["error"]
    ]

    # Single pass: classify MRs as already-active or needs-rebase.
    # rebase_limit is a per-repo concurrency cap -- "at most N MRs with
    # active pipelines" -- not a per-run burst.
    # Rebased MRs count as active with running/pending/success pipelines
    # (success = green and waiting to merge, still occupying a slot).
    already_active = 0
    needs_rebase: list[ProjectMergeRequest] = []
    for mr in merge_requests:
        pipelines = gl.get_merge_request_pipelines(mr)
        pipelines = [p for p in pipelines if p.status != PipelineStatus.SKIPPED]
        fresh_mr = gl.get_merge_request(mr.iid)
        if is_rebased(fresh_mr, gl):
            if pipelines and pipelines[0].status in {
                PipelineStatus.RUNNING,
                PipelineStatus.PENDING,
                PipelineStatus.SUCCESS,
            }:
                already_active += 1
            continue

        # OMM pending MRs are managed by _process_omm_group which uses
        # skip-ci rebases. Don't re-rebase them here with CI enabled.
        if OMM_PENDING in mr.labels:
            logging.debug(["rebase", gl.project.name, mr.iid, "skip-omm-pending"])
            continue

        _cancel_timed_out_pipelines(dry_run, gl, mr, pipelines, pipeline_timeout)

        if _should_skip_for_running_pipeline(pipelines, wait_for_pipeline):
            continue

        needs_rebase.append(mr)

    remaining_budget = max(rebase_limit - already_active, 0)
    rebases = 0
    for mr in needs_rebase:
        if rebases < remaining_budget:
            if _try_rebase(dry_run, gl, mr):
                rebases += 1
        else:
            logging.info([
                "rebase",
                gl.project.name,
                mr.iid,
                f"rebase limit reached ({already_active + rebases} active/in-flight, limit {rebase_limit}). will try next time",
            ])
            break
