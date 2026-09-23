from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import gitlab
from gitlab.const import PipelineStatus
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
)

from reconcile.gitlab_housekeeping.labels import MERGE_LABELS_PRIORITY
from reconcile.utils.datetime_util import from_utc_iso_format, utc_now

if TYPE_CHECKING:
    from gitlab.v4.objects import (
        ProjectCommit,
        ProjectMergeRequest,
        ProjectMergeRequestPipeline,
    )

    from reconcile.utils.gitlab_api import GitLabApi

merged_merge_requests = Counter(
    name="qontract_reconcile_merged_merge_requests",
    documentation="Number of merge requests that have been successfully merged in a repository",
    labelnames=["project_id", "self_service", "auto_merge", "app_sre", "onboarding"],
)

rebased_merge_requests = Counter(
    name="qontract_reconcile_rebased_merge_requests",
    documentation="Number of merge requests that have been successfully rebased in a repository",
    labelnames=["project_id"],
)

time_to_merge = Histogram(
    name="qontract_reconcile_time_to_merge_merge_request_minutes",
    documentation="The number of minutes it takes from when a merge request is mergeable until it is actually merged. This is an indicator of how busy the merge queue is.",
    labelnames=["project_id", "priority"],
    buckets=(5.0, 10.0, 20.0, 40.0, 60.0, float("inf")),
)

merge_requests_waiting = Gauge(
    name="qontract_reconcile_merge_requests_waiting",
    documentation="Number of merge requests that are in the queue waiting to be merged.",
    labelnames=["project_id"],
)

gitlab_token_expiration = Gauge(
    name="qontract_reconcile_gitlab_token_expiration_days",
    documentation="Time until personal access tokens expire",
    labelnames=["name"],
)

merge_requests_error = Gauge(
    name="qontract_reconcile_merge_requests_error",
    documentation="Number of merge requests stuck in an error state.",
    labelnames=["project_id"],
)

optimistic_merges = Counter(
    name="qontract_reconcile_optimistic_merges_total",
    documentation="MRs merged via the optimistic non-overlapping path",
    labelnames=["project_id"],
)

optimistic_merge_rejected = Counter(
    name="qontract_reconcile_optimistic_merge_rejected_total",
    documentation="MRs skipped during optimistic merge attempt",
    labelnames=["project_id", "reason"],
)

merge_batch_size_histogram = Histogram(
    name="qontract_reconcile_merge_batch_size",
    documentation="Number of MRs merged per loop iteration",
    labelnames=["project_id"],
    buckets=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, float("inf")),
)

omm_group_expanded = Counter(
    name="qontract_reconcile_omm_group_expanded_total",
    documentation="MRs added to an already-active OMM group after formation",
    labelnames=["project_id"],
)

EXPIRATION_DATE_FORMAT = "%Y-%m-%d"
SQUASH_OPTION_ALWAYS = "always"


class InsistOnPipelineError(Exception):
    """Exception used to retry a merge when the pipeline isn't yet complete."""


@dataclass
class ReloadToggle:
    """A class to toggle the reload of merge requests."""

    reload: bool = False


def _log_exception(ex: Exception) -> None:
    logging.info("Retrying - %s: %s", type(ex).__name__, ex)


def _calculate_time_since_approval(approved_at: str) -> float:
    """
    Returns the number of minutes since a MR has been approved.
    :param approved_at: the datetime the MR was approved in format %Y-%m-%dT%H:%M:%S.%fZ
    """
    time_since_approval = utc_now() - from_utc_iso_format(approved_at)
    return time_since_approval.total_seconds() / 60


def _get_approval_info(
    gl: GitLabApi, mr: ProjectMergeRequest
) -> tuple[str, str] | None:
    """Return (priority, approved_at) for a single MR by scanning label events.

    Returns None if no approval label is found.

    Unlike the approval scan in ``preprocess_merge_requests``, this does
    NOT enforce ``users_allowed_to_label`` — any label-add event counts.
    This is intentional: OMM-merged MRs already passed authorization
    during preprocessing in the loop that formed the group, so
    re-checking here would only add API calls for no safety benefit.
    The trade-off is that ``approved_at`` may differ slightly from what
    preprocessing would compute if an unauthorized user re-added a label
    after group formation, but the metric impact is negligible.
    """
    label_events = gl.get_merge_request_label_events(mr)
    labels = set(mr.labels)
    for label in reversed(label_events):
        if label.action != "add" or not label.label:
            continue
        label_name = label.label["name"]
        if label_name in MERGE_LABELS_PRIORITY:
            label_priority = min(
                MERGE_LABELS_PRIORITY.index(merge_label)
                for merge_label in MERGE_LABELS_PRIORITY
                if merge_label in labels
            )
            priority = f"{label_priority} - {MERGE_LABELS_PRIORITY[label_priority]}"
            return priority, label.created_at
    return None


def get_timed_out_pipelines(
    pipelines: list[ProjectMergeRequestPipeline],
    pipeline_timeout: int = 60,
) -> list[ProjectMergeRequestPipeline]:
    now = utc_now()

    pending_pipelines = [
        p
        for p in pipelines
        if p.status in {PipelineStatus.PENDING, PipelineStatus.RUNNING}
    ]

    if not pending_pipelines:
        return []

    timed_out_pipelines = []

    for p in pending_pipelines:
        update_time = from_utc_iso_format(p.updated_at)

        elapsed = (now - update_time).total_seconds()

        # pipeline_timeout converted in seconds
        if elapsed > pipeline_timeout * 60:
            timed_out_pipelines.append(p)

    return timed_out_pipelines


def clean_pipelines(
    dry_run: bool,
    gl: GitLabApi,
    fork_project_id: int,
    pipelines: list[ProjectMergeRequestPipeline],
) -> None:
    if not dry_run:
        gl_piplelines = gl.get_project_by_id(fork_project_id).pipelines

    for p in pipelines:
        logging.info(["canceling", p.web_url])
        if not dry_run:
            try:
                gl_piplelines.get(p.id, lazy=True).cancel()
            except gitlab.exceptions.GitlabPipelineCancelError as err:
                logging.error(
                    f"unable to cancel {p.web_url} - error message {err.error_message}"
                )


def _cancel_timed_out_pipelines(
    dry_run: bool,
    gl: GitLabApi,
    mr: ProjectMergeRequest,
    pipelines: list,
    pipeline_timeout: int | None,
) -> None:
    """Cancel pipelines that have exceeded the timeout threshold."""
    if pipeline_timeout is None:
        return
    timed_out_pipelines = get_timed_out_pipelines(pipelines, pipeline_timeout)
    if timed_out_pipelines:
        clean_pipelines(
            dry_run=dry_run,
            gl=gl,
            fork_project_id=mr.source_project_id,
            pipelines=timed_out_pipelines,
        )


def _should_skip_for_running_pipeline(pipelines: list, wait_for_pipeline: bool) -> bool:
    """Return True if the MR should be skipped because a pipeline is still running."""
    if not wait_for_pipeline:
        return False
    if not pipelines:
        return True
    return any(p.status == PipelineStatus.RUNNING for p in pipelines)


def is_rebased(mr: ProjectMergeRequest, gl: GitLabApi) -> bool:
    target_branch = mr.target_branch
    head = cast(
        "list[ProjectCommit]",
        gl.project.commits.list(
            ref_name=target_branch,
            per_page=1,
            page=1,
        ),
    )[0].id
    result = cast("dict", gl.project.repository_compare(mr.sha, head))
    return len(result["commits"]) == 0
