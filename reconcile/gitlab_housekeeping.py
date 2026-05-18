import logging
from collections.abc import (
    Iterable,
)
from collections.abc import (
    Set as AbstractSet,
)
from contextlib import suppress
from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
)
from enum import StrEnum
from operator import itemgetter
from typing import Any, cast

import gitlab
from gitlab.const import PipelineStatus
from gitlab.v4.objects import (
    ProjectCommit,
    ProjectIssue,
    ProjectMergeRequest,
    ProjectMergeRequestPipeline,
)
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
)
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.change_owners.change_types import ChangeTypePriority
from reconcile.utils.datetime_util import ensure_utc, from_utc_iso_format, utc_now
from reconcile.utils.gitlab_api import (
    GitLabApi,
    MRState,
    MRStatus,
)
from reconcile.utils.mr.labels import (
    APPROVED,
    AUTO_MERGE,
    AWAITING_APPROVAL,
    BLOCKED_BOT_ACCESS,
    CHANGES_REQUESTED,
    DO_NOT_MERGE_HOLD,
    DO_NOT_MERGE_PENDING_REVIEW,
    HOLD,
    LGTM,
    MERGE_ERROR,
    NEEDS_REBASE,
    ONBOARDING,
    PIPELINE_ERROR,
    SAAS_FILE_UPDATE,
    SELF_SERVICEABLE,
    prioritized_approval_label,
)
from reconcile.utils.sharding import is_in_shard
from reconcile.utils.state import State, init_state
from reconcile.utils.unleash import get_feature_variant

MERGE_LABELS_PRIORITY = [
    prioritized_approval_label(p.value) for p in ChangeTypePriority
] + [
    APPROVED,
    AUTO_MERGE,
    LGTM,
]
HOLD_LABELS = [
    AWAITING_APPROVAL,
    BLOCKED_BOT_ACCESS,
    CHANGES_REQUESTED,
    HOLD,
    DO_NOT_MERGE_HOLD,
    DO_NOT_MERGE_PENDING_REVIEW,
    NEEDS_REBASE,
]

ERROR_LABELS = [MERGE_ERROR, PIPELINE_ERROR]

TENANT_LABEL_PREFIX = "tenant-"

QONTRACT_INTEGRATION = "gitlab-housekeeping"
EXPIRATION_DATE_FORMAT = "%Y-%m-%d"
SQUASH_OPTION_ALWAYS = "always"

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


class RebaseStrategy(StrEnum):
    ACTIVE_CAP = "active-cap"
    ACTIVE_CAP_MULTI_MERGE = "active-cap-multi-merge"
    TOP_K = "top-k"
    OLD_BURST = "old-burst"


REBASE_STRATEGY_TOGGLE = "gitlab-housekeeping-rebase-strategy"
DEFAULT_REBASE_STRATEGY = RebaseStrategy.OLD_BURST


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


class InsistOnPipelineError(Exception):
    """Exception used to retry a merge when the pipeline isn't yet complete."""


@dataclass
class ReloadToggle:
    """A class to toggle the reload of merge requests."""

    reload: bool = False


def get_tenant_labels(mr: ProjectMergeRequest) -> set[str]:
    return {label for label in mr.labels if label.startswith(TENANT_LABEL_PREFIX)}


def is_eligible_for_optimistic_merge(mr: ProjectMergeRequest) -> bool:
    return bool(get_tenant_labels(mr))


def has_overlapping_labels(mr_labels: set[str], merged_labels: set[str]) -> bool:
    return bool(mr_labels & merged_labels)


def _log_exception(ex: Exception) -> None:
    logging.info("Retrying - %s: %s", type(ex).__name__, ex)


def _calculate_time_since_approval(approved_at: str) -> float:
    """
    Returns the number of minutes since a MR has been approved.
    :param approved_at: the datetime the MR was approved in format %Y-%m-%dT%H:%M:%S.%fZ
    """
    time_since_approval = utc_now() - from_utc_iso_format(approved_at)
    return time_since_approval.total_seconds() / 60


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


def verify_on_demand_tests(
    dry_run: bool,
    mr: ProjectMergeRequest,
    must_pass: Iterable[str],
    gl: GitLabApi,
    state: State,
) -> bool:
    """
    Check if MR has passed all necessary test jobs and add comments to indicate test results.
    """
    pipelines = gl.get_merge_request_pipelines(mr)
    running_pipelines = [p for p in pipelines if p.status == PipelineStatus.RUNNING]
    if running_pipelines:
        # wait for pipelines completion
        return False

    commit = next(mr.commits())
    fork_project = gl.get_project_by_id(mr.source_project_id)
    statuses = fork_project.commits.get(commit.id).statuses.list()
    test_state = {s.name: s.status for s in statuses}
    remaining_tests = [t for t in must_pass if test_state.get(t) != "success"]
    state_key = f"{gl.project.path_with_namespace}/{mr.iid}/{commit.id}"
    # only add comment when state changes
    state_change = state.get(state_key, None) != remaining_tests

    if remaining_tests:
        logging.info([
            "on-demand tests",
            "add comment",
            gl.project.name,
            mr.iid,
            commit.id,
        ])
        if not dry_run and state_change:
            markdown_report = (
                f"On-demand Tests: \n\n For latest [commit]({commit.web_url}) You will need to pass following test jobs to get this MR merged.\n\n"
                f"Add a comment with `/test [test_name]` to trigger a test; multiple tests can be triggered from the same comment: repeat the `/test [test_name]` command separated by lines.\n\n"
            )
            markdown_report += f"* {', '.join(remaining_tests)}\n\n"
            markdown_report += "An update of the MR will reset the on-demand tests. Consider running them once the MR is REVIEWED and no more code changes are required.\n\n"
            gl.delete_merge_request_comments(mr, startswith="On-demand Tests:")
            gl.add_comment_to_merge_request(mr, markdown_report)
            state.add(state_key, remaining_tests, force=True)
        return False
    else:
        # no remain_tests, pass the check
        logging.info([
            "on-demand tests",
            "check pass",
            gl.project.name,
            mr.iid,
            commit.id,
        ])
        if not dry_run and state_change:
            markdown_report = f"On-demand Tests: \n\n All necessary tests have passed for latest [commit]({commit.web_url})\n"
            gl.delete_merge_request_comments(mr, startswith="On-demand Tests:")
            gl.add_comment_to_merge_request(mr, markdown_report)
            state.add(state_key, remaining_tests, force=True)
        return True


def close_item(
    dry_run: bool,
    gl: GitLabApi,
    enable_closing: bool,
    item_type: str,
    item: ProjectIssue | ProjectMergeRequest,
) -> None:
    if enable_closing:
        logging.info([
            "close_item",
            gl.project.name,
            item_type,
            item.attributes.get("iid"),
        ])
        if not dry_run:
            gl.close(item)
    else:
        logging.debug([
            "'enable_closing' is not enabled to close item",
            gl.project.name,
            item_type,
            item.attributes.get("iid"),
        ])


def handle_stale_items(
    dry_run: bool,
    gl: GitLabApi,
    days_interval: int,
    enable_closing: bool,
    items: Iterable[ProjectIssue | ProjectMergeRequest],
    item_type: str,
) -> None:
    LABEL = "stale"  # noqa: N806

    now = utc_now()
    for item in items:
        if AUTO_MERGE in item.labels:
            if item.merge_status == MRStatus.UNCHECKED:
                # this call triggers a status recheck
                item = gl.get_merge_request(item.iid)
            if item.merge_status == MRStatus.CANNOT_BE_MERGED:
                close_item(dry_run, gl, enable_closing, item_type, item)
        update_date = from_utc_iso_format(item.updated_at)

        # if item is over days_interval
        current_interval = now.date() - update_date.date()
        if current_interval > timedelta(days=days_interval):
            # if item does not have 'stale' label - add it
            if LABEL not in item.labels:
                logging.info(["add_label", gl.project.name, item_type, item.iid, LABEL])
                if not dry_run:
                    gl.add_label_with_note(item, LABEL)
            # if item has 'stale' label - close it
            else:
                close_item(dry_run, gl, enable_closing, item_type, item)
        # if item is under days_interval
        else:
            if LABEL not in item.labels:
                continue

            # if item has 'stale' label - check the notes
            # TODO: add request count metrics and maybe server side filter to reduce requests
            cancel_notes = [
                n
                for n in item.notes.list(iterator=True)
                if n.attributes.get("body") == f"/{LABEL} cancel"
            ]
            if not cancel_notes:
                continue

            latest_cancel_note_date = max(
                from_utc_iso_format(note.updated_at) for note in cancel_notes
            )
            # if the latest cancel note is under
            # days_interval - remove 'stale' label
            current_interval = now.date() - latest_cancel_note_date.date()
            if current_interval <= timedelta(days=days_interval):
                logging.info([
                    "remove_label",
                    gl.project.name,
                    item_type,
                    item.iid,
                    LABEL,
                ])
                if not dry_run:
                    gl.remove_label(item, LABEL)


def is_good_to_merge(labels: Iterable[str]) -> bool:
    return any(m in MERGE_LABELS_PRIORITY for m in labels) and not any(
        b in HOLD_LABELS for b in labels
    )


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


def get_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    state: State,
    users_allowed_to_label: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    mrs = gl.get_merge_requests(state=MRState.OPENED)
    return preprocess_merge_requests(
        dry_run=dry_run,
        gl=gl,
        project_merge_requests=mrs,
        state=state,
        users_allowed_to_label=users_allowed_to_label,
    )


def preprocess_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    state: State,
    users_allowed_to_label: Iterable[str] | None = None,
    must_pass: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    results = []
    for mr in project_merge_requests:
        if mr.merge_status in {
            MRStatus.CANNOT_BE_MERGED,
            MRStatus.CANNOT_BE_MERGED_RECHECK,
        }:
            continue
        if mr.draft:
            continue
        if len(mr.commits()) == 0:
            continue

        if must_pass and not verify_on_demand_tests(
            dry_run=dry_run,
            mr=mr,
            must_pass=must_pass,
            gl=gl,
            state=state,
        ):
            continue

        labels = set(mr.labels)
        if not labels:
            continue

        if (
            SAAS_FILE_UPDATE in labels or SELF_SERVICEABLE in labels
        ) and LGTM in labels:
            logging.warning(
                f"[{gl.project.name}/{mr.iid}] 'lgtm' label not "
                + "suitable for self serviceable MRs. removing 'lgtm' label"
            )
            if not dry_run:
                gl.remove_label(mr, LGTM)
            continue

        label_events = gl.get_merge_request_label_events(mr)
        approval_found = False
        labels_by_unauthorized_users = set()
        labels_by_authorized_users = set()
        for label in reversed(label_events):
            if label.action == "add":
                if not label.label:
                    # label doesn't exist anymore, may be remove later
                    continue
                label_name = label.label["name"]
                added_by = label.user["username"]
                if users_allowed_to_label and added_by not in (
                    set(users_allowed_to_label) | {gl.user.username}
                ):
                    # label added by an unauthorized user. remove it maybe later
                    labels_by_unauthorized_users.add(label_name)
                    continue

                # label added by an authorized user, so don't delete it
                labels_by_authorized_users.add(label_name)

                if label_name in MERGE_LABELS_PRIORITY and not approval_found:
                    approval_found = True
                    approved_at = label.created_at
                    approved_by = added_by

        bad_labels = (
            labels_by_unauthorized_users - labels_by_authorized_users
        ) & labels
        for bad_label in bad_labels:
            logging.warning(
                f"[{gl.project.name}/{mr.iid}] someone added a label who "
                f"isn't allowed. removing label {bad_label}"
            )
        if bad_labels and not dry_run:
            gl.remove_labels(mr, bad_labels)

        labels = set(mr.labels)
        if not is_good_to_merge(labels):
            continue

        label_priority = min(
            MERGE_LABELS_PRIORITY.index(merge_label)
            for merge_label in MERGE_LABELS_PRIORITY
            if merge_label in labels
        )

        item = {
            "mr": mr,
            "label_priority": label_priority,
            "priority": f"{label_priority} - {MERGE_LABELS_PRIORITY[label_priority]}",
            "approved_at": approved_at,
            "approved_by": approved_by,
            "error": any(label in ERROR_LABELS for label in labels),
        }
        results.append(item)

    results.sort(key=itemgetter("label_priority", "approved_at"))

    return results


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
        RebaseStrategy.TOP_K: _rebase_merge_requests_top_k,
        RebaseStrategy.OLD_BURST: _rebase_merge_requests_old_burst,
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


def _try_rebase(
    dry_run: bool,
    gl: GitLabApi,
    mr: ProjectMergeRequest,
) -> bool:
    """Attempt to rebase an MR. Returns True on success, False on failure."""
    try:
        logging.info(["rebase", gl.project.name, mr.iid])
        if not dry_run:
            mr.rebase()
            rebased_merge_requests.labels(mr.target_project_id).inc()
        return True
    except gitlab.exceptions.GitlabMRRebaseError as e:
        logging.error(f"unable to rebase {mr.iid}: {e}")
        return False


def _rebase_merge_requests_top_k(
    dry_run: bool,
    gl: GitLabApi,
    rebase_limit: int,
    state: State,
    pipeline_timeout: int | None = None,
    wait_for_pipeline: bool = False,
    users_allowed_to_label: Iterable[str] | None = None,
) -> None:
    """Top-k strategy: only evaluate the first rebase_limit MRs in priority
    order.  The queue is already sorted by priority, so slicing to K
    guarantees at most K MRs are rebased across all runs.
    Error MRs are filtered before slicing so they don't consume slots."""
    merge_requests = [
        item["mr"]
        for item in get_merge_requests(
            dry_run=dry_run,
            gl=gl,
            state=state,
            users_allowed_to_label=users_allowed_to_label,
        )
        if not item["error"]
    ][:rebase_limit]

    for mr in merge_requests:
        if is_rebased(mr, gl):
            continue

        pipelines = gl.get_merge_request_pipelines(mr)
        _cancel_timed_out_pipelines(dry_run, gl, mr, pipelines, pipeline_timeout)

        if _should_skip_for_running_pipeline(pipelines, wait_for_pipeline):
            continue

        _try_rebase(dry_run, gl, mr)


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
        if is_rebased(mr, gl):
            if pipelines and pipelines[0].status in {
                PipelineStatus.RUNNING,
                PipelineStatus.PENDING,
                PipelineStatus.SUCCESS,
            }:
                already_active += 1
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


def _rebase_merge_requests_old_burst(
    dry_run: bool,
    gl: GitLabApi,
    rebase_limit: int,
    state: State,
    pipeline_timeout: int | None = None,
    wait_for_pipeline: bool = False,
    users_allowed_to_label: Iterable[str] | None = None,
) -> None:
    """Old-burst strategy: scan the full queue and rebase up to rebase_limit
    MRs that are not already rebased.  This is a simple per-run burst
    counter — it does not consider active pipelines."""
    rebases = 0
    merge_requests = [
        item["mr"]
        for item in get_merge_requests(
            dry_run=dry_run,
            gl=gl,
            state=state,
            users_allowed_to_label=users_allowed_to_label,
        )
        if not item["error"]
    ]
    for mr in merge_requests:
        if is_rebased(mr, gl):
            continue

        pipelines = gl.get_merge_request_pipelines(mr)
        _cancel_timed_out_pipelines(dry_run, gl, mr, pipelines, pipeline_timeout)

        if _should_skip_for_running_pipeline(pipelines, wait_for_pipeline):
            continue

        if rebases < rebase_limit:
            if _try_rebase(dry_run, gl, mr):
                rebases += 1
        else:
            logging.info([
                "rebase",
                gl.project.name,
                mr.iid,
                "rebase limit reached for this reconcile loop. will try next time",
            ])


# TODO: this retry is catching all exceptions, which isn't good. _log_exceptions is
# being added so we can track whether it's catching anything other than what appears to
# be the intended case of retrying with "insist". Once we have some additional data,
# we can change this to retry on a small set of exceptions including
# InsistOnPipelineException.


@retry(max_attempts=10, hook=_log_exception)
def merge_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    reload_toggle: ReloadToggle,
    merge_limit: int,
    rebase: bool,
    app_sre_usernames: AbstractSet[str],
    state: State,
    pipeline_timeout: int | None = None,
    insist: bool = False,
    wait_for_pipeline: bool = False,
    users_allowed_to_label: Iterable[str] | None = None,
    must_pass: Iterable[str] | None = None,
    multi_merge: bool = False,
) -> None:
    merges = 0
    if reload_toggle.reload:
        project_merge_requests = gl.get_merge_requests(state=MRState.OPENED)
    merge_requests = preprocess_merge_requests(
        dry_run=dry_run,
        gl=gl,
        project_merge_requests=project_merge_requests,
        state=state,
        users_allowed_to_label=users_allowed_to_label,
        must_pass=must_pass,
    )
    merge_requests_waiting.labels(gl.project.id).set(len(merge_requests))
    merge_requests_error.labels(gl.project.id).set(
        sum(1 for item in merge_requests if item["error"])
    )

    merged_labels: set[str] = set()
    first_merge_done = False

    for merge_request in merge_requests:
        mr: ProjectMergeRequest = merge_request["mr"]

        if merge_request["error"]:
            logging.info(["skip merge", gl.project.name, mr.iid])
            continue

        if rebase:
            if first_merge_done:
                if not multi_merge:
                    break
                if not is_eligible_for_optimistic_merge(mr):
                    optimistic_merge_rejected.labels(
                        project_id=mr.target_project_id, reason="ineligible"
                    ).inc()
                    continue
                mr_labels = get_tenant_labels(mr)
                if has_overlapping_labels(mr_labels, merged_labels):
                    optimistic_merge_rejected.labels(
                        project_id=mr.target_project_id, reason="overlap"
                    ).inc()
                    continue
            elif not is_rebased(mr, gl):
                continue

        pipelines = gl.get_merge_request_pipelines(mr)
        if not pipelines:
            continue

        # If pipeline_timeout is None no pipeline will be canceled
        if pipeline_timeout is not None:
            timed_out_pipelines = get_timed_out_pipelines(pipelines, pipeline_timeout)
            if timed_out_pipelines:
                clean_pipelines(
                    dry_run=dry_run,
                    gl=gl,
                    fork_project_id=mr.source_project_id,
                    pipelines=timed_out_pipelines,
                )

        if wait_for_pipeline:
            running_pipelines = [
                p for p in pipelines if p.status == PipelineStatus.RUNNING
            ]
            if running_pipelines:
                if not first_merge_done and insist:
                    # Retry only before the first merge — the @retry decorator
                    # resets all local state, which would discard multi-merge
                    # progress.
                    reload_toggle.reload = True
                    raise InsistOnPipelineError(
                        f"Pipelines for merge request in project '{gl.project.name}' have not completed yet: {mr.iid}"
                    )
                continue

        last_pipeline_result = pipelines[0].status
        if last_pipeline_result != PipelineStatus.SUCCESS:
            continue

        logging.info(["merge", gl.project.name, mr.iid])
        if not dry_run and merges < merge_limit:
            try:
                squash = (gl.project.squash_option == SQUASH_OPTION_ALWAYS) or mr.squash
                if first_merge_done and rebase:
                    mr.rebase(skip_ci=True)

                mr.merge(squash=squash)
                labels = mr.labels
                merged_merge_requests.labels(
                    project_id=mr.target_project_id,
                    self_service=SELF_SERVICEABLE in labels,
                    auto_merge=AUTO_MERGE in labels,
                    app_sre=mr.author["username"] in app_sre_usernames,
                    onboarding=ONBOARDING in labels,
                ).inc()
                time_to_merge.labels(
                    project_id=mr.target_project_id, priority=merge_request["priority"]
                ).observe(_calculate_time_since_approval(merge_request["approved_at"]))
                if first_merge_done and rebase:
                    optimistic_merges.labels(
                        project_id=mr.target_project_id
                    ).inc()

                merged_labels.update(get_tenant_labels(mr))
                first_merge_done = True
                merges += 1
            except gitlab.exceptions.GitlabMRRebaseError as e:
                logging.warning(f"optimistic rebase failed for {mr.iid}: {e}")
                optimistic_merge_rejected.labels(
                    project_id=mr.target_project_id, reason="rebase_failed"
                ).inc()
            except gitlab.exceptions.GitlabMRClosedError as e:
                logging.error(f"unable to merge {mr.iid}: {e}")
                if not dry_run:
                    gl.add_label_to_merge_request(mr, MERGE_ERROR)
                if first_merge_done:
                    optimistic_merge_rejected.labels(
                        project_id=mr.target_project_id, reason="merge_rejected"
                    ).inc()

    merge_batch_size_histogram.labels(project_id=gl.project.id).observe(merges)


def run_error_healthcheck(
    dry_run: bool,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    consecutive_failure_limit: int = 3,
) -> None:
    """Check error labels for queue-eligible MRs. Apply/remove
    pipeline-error based on consecutive failure count, and remove
    merge-error if any new notes have been posted since the label was applied."""
    for mr in project_merge_requests:
        if mr.draft:
            continue

        if mr.merge_status in {
            MRStatus.CANNOT_BE_MERGED,
            MRStatus.CANNOT_BE_MERGED_RECHECK,
        }:
            continue

        if not is_good_to_merge(mr.labels):
            continue

        pipelines = gl.get_merge_request_pipelines(mr)
        if not pipelines:
            continue

        labels = set(mr.labels)

        has_pipeline_error = PIPELINE_ERROR in labels
        is_healthy = check_pipeline_health(pipelines, consecutive_failure_limit)

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
                    and not note.system
                    and note.author["username"] != gl.user.username
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


def get_app_sre_usernames(gl: GitLabApi) -> set[str]:
    return {u.username for u in gl.get_app_sre_group_users()}


def publish_access_token_expiration_metrics(gl: GitLabApi) -> None:
    pats = gl.get_personal_access_tokens()

    for pat in pats:
        if pat.active:
            expiration_date = ensure_utc(
                datetime.strptime(pat.expires_at, EXPIRATION_DATE_FORMAT)  # noqa: DTZ007
            )
            days_until_expiration = expiration_date.date() - utc_now().date()
            gitlab_token_expiration.labels(pat.name).set(days_until_expiration.days)
        else:
            with suppress(KeyError, ValueError):
                # there's no publicly exposed method to determine if a label exists for a gauge
                # which is why I wrapped the error like this
                gitlab_token_expiration.remove(pat.name)


def run(dry_run: bool, wait_for_pipeline: bool) -> None:
    default_days_interval = 15
    default_limit = 8
    default_merge_limit = 8
    default_consecutive_failure_limit = 3
    default_enable_closing = False
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    with GitLabApi(instance, settings=settings) as gl:
        publish_access_token_expiration_metrics(gl)
    repos = queries.get_repos_gitlab_housekeeping(server=instance["url"])
    repos = [r for r in repos if is_in_shard(r["url"])]
    app_sre_usernames: set[str] = set()
    rebase_strategy = get_rebase_strategy()
    multi_merge = rebase_strategy == RebaseStrategy.ACTIVE_CAP_MULTI_MERGE
    state = init_state(QONTRACT_INTEGRATION)

    for repo in repos:
        hk = repo["housekeeping"]
        project_url = repo["url"]
        days_interval = hk.get("days_interval") or default_days_interval
        enable_closing = hk.get("enable_closing") or default_enable_closing
        limit = hk.get("limit") or default_limit
        merge_limit = hk.get("merge_limit") or default_merge_limit
        consecutive_failure_limit = (
            hk.get("consecutive_failure_limit") or default_consecutive_failure_limit
        )
        pipeline_timeout = hk.get("pipeline_timeout")

        labels_allowed = hk.get("labels_allowed")
        users_allowed_to_label = (
            None
            if not labels_allowed
            else {
                u["org_username"] for la in labels_allowed for u in la["role"]["users"]
            }
        )
        with GitLabApi(instance, project_url=project_url, settings=settings) as gl:
            if not app_sre_usernames:
                app_sre_usernames = get_app_sre_usernames(gl)
            issues = gl.get_issues(state=MRState.OPENED)
            handle_stale_items(
                dry_run,
                gl,
                days_interval,
                enable_closing,
                issues,
                "issue",
            )
            opened_merge_requests = gl.get_merge_requests(state=MRState.OPENED)
            handle_stale_items(
                dry_run,
                gl,
                days_interval,
                enable_closing,
                opened_merge_requests,
                "merge-request",
            )
            project_merge_requests = [
                mr for mr in opened_merge_requests if mr.state == MRState.OPENED
            ]
            try:
                run_error_healthcheck(
                    dry_run=dry_run,
                    gl=gl,
                    project_merge_requests=project_merge_requests,
                    consecutive_failure_limit=consecutive_failure_limit,
                )
            except Exception:
                logging.exception(
                    "error healthcheck failed, continuing with merge/rebase"
                )
            reload_toggle = ReloadToggle(reload=False)
            rebase = hk.get("rebase")
            must_pass = hk.get("must_pass")
            try:
                merge_merge_requests(
                    dry_run=dry_run,
                    gl=gl,
                    project_merge_requests=project_merge_requests,
                    reload_toggle=reload_toggle,
                    merge_limit=merge_limit,
                    rebase=rebase,
                    app_sre_usernames=app_sre_usernames,
                    state=state,
                    pipeline_timeout=pipeline_timeout,
                    insist=True,
                    wait_for_pipeline=wait_for_pipeline,
                    users_allowed_to_label=users_allowed_to_label,
                    must_pass=must_pass,
                    multi_merge=multi_merge,
                )
            except Exception:
                logging.error(
                    "All retries failed, trying to rerun merge_merge_requests() again."
                )
                merge_merge_requests(
                    dry_run=dry_run,
                    gl=gl,
                    project_merge_requests=project_merge_requests,
                    reload_toggle=reload_toggle,
                    merge_limit=merge_limit,
                    rebase=rebase,
                    app_sre_usernames=app_sre_usernames,
                    state=state,
                    pipeline_timeout=pipeline_timeout,
                    insist=False,
                    wait_for_pipeline=wait_for_pipeline,
                    users_allowed_to_label=users_allowed_to_label,
                    must_pass=must_pass,
                    multi_merge=multi_merge,
                )
            if rebase:
                rebase_merge_requests(
                    dry_run=dry_run,
                    gl=gl,
                    rebase_limit=limit,
                    state=state,
                    pipeline_timeout=pipeline_timeout,
                    wait_for_pipeline=wait_for_pipeline,
                    users_allowed_to_label=users_allowed_to_label,
                    strategy=rebase_strategy,
                )
