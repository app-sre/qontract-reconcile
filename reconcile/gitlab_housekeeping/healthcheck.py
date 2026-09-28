from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import gitlab
from gitlab.const import PipelineStatus

from reconcile.gitlab_housekeeping.labels import is_good_to_merge
from reconcile.utils.datetime_util import from_utc_iso_format
from reconcile.utils.gitlab_api import MRStatus
from reconcile.utils.mr.labels import (
    MERGE_ERROR,
    PIPELINE_ERROR,
    REBASE_ERROR,
)

if TYPE_CHECKING:
    from gitlab.v4.objects import (
        ProjectMergeRequest,
        ProjectMergeRequestPipeline,
    )

    from reconcile.utils.gitlab_api import GitLabApi

PIPELINE_FAILURE_STATUSES = {PipelineStatus.FAILED}


def check_pipeline_health(
    pipelines: list[ProjectMergeRequestPipeline],
    consecutive_failure_limit: int = 3,
) -> bool:
    """Return True if MR is healthy (should stay in queue).

    Return False if last `consecutive_failure_limit` pipelines all
    ended in a non-success terminal state (FAILED).
    """
    pipeline_failure_window = pipelines[:consecutive_failure_limit]
    if len(pipeline_failure_window) < consecutive_failure_limit:
        return True
    return not all(
        p.status in PIPELINE_FAILURE_STATUSES for p in pipeline_failure_window
    )


def run_error_healthcheck(
    dry_run: bool,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    consecutive_failure_limit: int = 3,
    *,
    pipeline_cache: dict[int, list[ProjectMergeRequestPipeline]],
) -> None:
    """Check error labels for queue-eligible MRs. Apply/remove
    rebase-error based on merge_error field from .get(),
    pipeline-error based on consecutive failure count, and remove
    merge-error if any new notes have been posted since the label was applied."""
    for mr in project_merge_requests:
        if mr.draft:
            continue

        # Don't skip on cannot_be_merged/cannot_be_merged_recheck: that's
        # exactly the state a real merge conflict produces, and it's the case
        # the merge_error/rebase-error check below exists to catch. Skipping
        # here means a conflicting MR can never be flagged. No log at this
        # point though -- cannot_be_merged_recheck is a transient state that
        # GitLab sets for nearly every open MR on every reconcile cycle
        # before approval is even checked; logging here was tried in #5733
        # and reverted in #5742 for producing ~1,700 log lines/hour.

        if not is_good_to_merge(mr.labels):
            continue

        if mr.merge_status in {
            MRStatus.CANNOT_BE_MERGED,
            MRStatus.CANNOT_BE_MERGED_RECHECK,
        }:
            logging.debug([
                "error-healthcheck",
                "unmergeable",
                gl.project.name,
                mr.iid,
                f"merge_status={mr.merge_status}",
            ])

        labels = set(mr.labels)

        has_rebase_error = REBASE_ERROR in labels
        try:
            fresh = gl.get_merge_request(mr.iid)
        except gitlab.exceptions.GitlabGetError as e:
            logging.warning([
                "error-healthcheck",
                "rebase-status-refresh-failed",
                gl.project.name,
                mr.iid,
                str(e),
            ])
            rebase_failed = has_rebase_error
        else:
            fresh_merge_error = getattr(fresh, "merge_error", None)
            rebase_failed = bool(
                fresh_merge_error and "Rebase failed" in fresh_merge_error
            )

        if rebase_failed and not has_rebase_error:
            logging.warning([
                "add_label",
                REBASE_ERROR,
                gl.project.name,
                mr.iid,
                fresh_merge_error,
            ])
            if not dry_run:
                gl.add_label_to_merge_request(mr, REBASE_ERROR)
            continue
        elif not rebase_failed and has_rebase_error:
            logging.info([
                "remove_label",
                REBASE_ERROR,
                gl.project.name,
                mr.iid,
            ])
            if not dry_run:
                gl.remove_label(mr, REBASE_ERROR)

        pipelines = gl.get_merge_request_pipelines(mr)
        pipeline_cache[mr.iid] = pipelines
        if not pipelines:
            continue

        terminal_pipelines = [
            p
            for p in pipelines
            if p.status
            in {
                PipelineStatus.SUCCESS,
                PipelineStatus.FAILED,
                PipelineStatus.CANCELED,
                PipelineStatus.SKIPPED,
            }
        ]
        if not terminal_pipelines:
            continue

        has_pipeline_error = PIPELINE_ERROR in labels
        is_healthy = check_pipeline_health(
            terminal_pipelines, consecutive_failure_limit
        )

        if not is_healthy and not has_pipeline_error:
            logging.warning([
                "add_label",
                PIPELINE_ERROR,
                gl.project.name,
                mr.iid,
            ])
            if not dry_run:
                gl.add_label_to_merge_request(mr, PIPELINE_ERROR)
        elif is_healthy and has_pipeline_error:
            logging.info([
                "remove_label",
                PIPELINE_ERROR,
                gl.project.name,
                mr.iid,
            ])
            if not dry_run:
                gl.remove_label(mr, PIPELINE_ERROR)

        if MERGE_ERROR in labels:
            label_events = gl.get_merge_request_label_events(mr)
            merge_error_added_at = None
            for event in reversed(label_events):
                if (
                    event.action == "add"
                    and event.label
                    and event.label["name"] == MERGE_ERROR
                ):
                    merge_error_added_at = event.created_at
                    break

            if merge_error_added_at:
                latest_notes = mr.notes.list(
                    order_by="created_at", sort="desc", per_page=1
                )
                if any(
                    from_utc_iso_format(note.created_at)
                    > from_utc_iso_format(merge_error_added_at)
                    for note in latest_notes
                ):
                    logging.info([
                        "remove_label",
                        MERGE_ERROR,
                        gl.project.name,
                        mr.iid,
                        "new notes after merge-error label",
                    ])
                    if not dry_run:
                        gl.remove_label(mr, MERGE_ERROR)
