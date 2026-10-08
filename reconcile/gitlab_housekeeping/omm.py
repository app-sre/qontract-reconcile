from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from operator import itemgetter
from typing import TYPE_CHECKING, Any, cast

import gitlab
from gitlab.const import PipelineStatus

from reconcile.gitlab_housekeeping.helpers import (
    SQUASH_OPTION_ALWAYS,
    calculate_time_since_approval,
    clean_pipelines,
    get_timed_out_pipelines,
    is_rebased,
    merged_merge_requests,
    omm_group_expanded,
    optimistic_merge_rejected,
    optimistic_merges,
    time_to_merge,
)
from reconcile.gitlab_housekeeping.labels import (
    ERROR_LABELS,
    HOLD_LABELS,
    MERGE_LABELS_PRIORITY,
    get_tenant_labels,
    has_overlapping_labels,
    is_eligible_for_optimistic_merge,
)
from reconcile.utils.datetime_util import from_utc_iso_format, utc_now
from reconcile.utils.gitlab_api import MRState
from reconcile.utils.mr.labels import (
    AUTO_MERGE,
    MERGE_ERROR,
    OMM_GROUP_LEAD,
    OMM_PENDING,
    ONBOARDING,
    REBASE_ERROR,
    SELF_SERVICEABLE,
)
from reconcile.utils.unleash import get_feature_variant

if TYPE_CHECKING:
    from collections.abc import Set as AbstractSet

    from gitlab.v4.objects import (
        ProjectMergeRequest,
    )

    from reconcile.utils.gitlab_api import GitLabApi

OMM_MAX_INTERVAL_TOGGLE = "gitlab-housekeeping-omm-max-interval"
DEFAULT_OMM_MAX_INTERVAL_MINUTES = 5


def get_omm_max_interval() -> timedelta:
    """Resolve the OMM group window duration from Unleash."""
    value = get_feature_variant(
        OMM_MAX_INTERVAL_TOGGLE,
        default_variant=str(DEFAULT_OMM_MAX_INTERVAL_MINUTES),
    )
    try:
        return timedelta(minutes=int(value))
    except ValueError, TypeError:
        logging.warning(
            f"Invalid omm-max-interval variant '{value}', "
            f"falling back to {DEFAULT_OMM_MAX_INTERVAL_MINUTES}m"
        )
        return timedelta(minutes=DEFAULT_OMM_MAX_INTERVAL_MINUTES)


def get_omm_group_lead(gl: GitLabApi) -> ProjectMergeRequest | None:
    """Find the active group lead — a recently merged MR with the omm-group-lead label."""
    mrs = gl.project.mergerequests.list(
        state=MRState.MERGED,
        labels=[OMM_GROUP_LEAD],
        order_by="updated_at",
        sort="desc",
        per_page=1,
        get_all=False,
    )
    return mrs[0] if mrs else None


def get_omm_pending_mrs(gl: GitLabApi) -> list[ProjectMergeRequest]:
    """Return all open MRs with the omm-pending label."""
    return gl.project.mergerequests.list(
        state=MRState.OPENED,
        labels=[OMM_PENDING],
        get_all=True,
    )


def apply_omm_pending(
    dry_run: bool,
    gl: GitLabApi,
    mrs: list[ProjectMergeRequest],
) -> list[ProjectMergeRequest]:
    """Apply omm-pending label and kick rebases for group candidates.

    Returns the subset of MRs that were successfully retained in the group
    (i.e. whose rebase did not fail). In dry-run mode all candidates are
    returned as retained since no mutations are performed.
    """
    retained: list[ProjectMergeRequest] = []
    for mr in mrs:
        logging.info(["omm-group", "add-pending", gl.project.name, mr.iid])
        if not dry_run:
            gl.add_label_to_merge_request(mr, OMM_PENDING)
            try:
                logging.info([
                    "omm-group",
                    "skip-ci-rebase-at-formation",
                    gl.project.name,
                    mr.iid,
                ])
                mr.rebase(skip_ci=True)
            except gitlab.exceptions.GitlabMRRebaseError:
                logging.warning([
                    "omm-group",
                    "rebase-failed-at-formation",
                    gl.project.name,
                    mr.iid,
                ])
                gl.remove_label(mr, OMM_PENDING)
                gl.add_label_to_merge_request(mr, REBASE_ERROR)
                optimistic_merge_rejected.labels(
                    project_id=mr.target_project_id,
                    reason="rebase_failed",
                ).inc()
                continue
        retained.append(mr)
    return retained


def apply_omm_group_lead(
    dry_run: bool,
    gl: GitLabApi,
    mr: ProjectMergeRequest,
) -> None:
    """Tag a just-merged MR as the group lead."""
    logging.info(["omm-group", "set-lead", gl.project.name, mr.iid])
    if not dry_run:
        gl.add_label_to_merge_request(mr, OMM_GROUP_LEAD)


def clear_omm_group(
    dry_run: bool,
    gl: GitLabApi,
    lead: ProjectMergeRequest | None = None,
    pending: list[ProjectMergeRequest] | None = None,
) -> None:
    """Remove all OMM labels — close the group.

    Also cleans up stale omm-pending labels on MRs that were closed,
    merged externally, or otherwise left the OPENED state while the
    group was active.

    Accepts optional pre-fetched ``lead`` and ``pending`` to avoid
    redundant API calls when the caller already has them.
    """
    if lead is None:
        lead = get_omm_group_lead(gl)
    if lead:
        logging.info(["omm-group", "clear-lead", gl.project.name, lead.iid])
        if not dry_run:
            gl.remove_label(lead, OMM_GROUP_LEAD)

    if pending is None:
        pending = get_omm_pending_mrs(gl)
    for mr in pending:
        logging.info(["omm-group", "clear-pending", gl.project.name, mr.iid])
        if not dry_run:
            gl.remove_label(mr, OMM_PENDING)

    for state in (MRState.CLOSED, MRState.MERGED):
        stale = gl.project.mergerequests.list(
            state=state,
            labels=[OMM_PENDING],
            get_all=True,
        )
        for mr in stale:
            logging.info(["omm-group", "clear-stale", gl.project.name, mr.iid])
            if not dry_run:
                gl.remove_label(mr, OMM_PENDING)


def _bot_commit_emails(gl: GitLabApi) -> set[str]:
    """Emails the rebase API writes as committer. Empty strings never match."""
    emails: set[str] = set()
    user = getattr(gl, "user", None)
    if user is None:
        return emails
    for raw in (
        getattr(user, "commit_email", None),
        getattr(user, "email", None),
    ):
        if isinstance(raw, str) and raw.strip():
            emails.add(raw.strip().lower())
    return emails


def _event_label_name(event: Any) -> str | None:
    label = getattr(event, "label", None)
    if isinstance(label, dict):
        name = label.get("name")
    else:
        name = getattr(label, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _omm_pending_on_intervals(
    gl: GitLabApi,
    mr: ProjectMergeRequest,
) -> list[tuple[datetime, datetime | None]] | None:
    """Stretches when omm-pending was on. None if the events cannot be read.

    An open interval (end is None) means the label is still on.
    """
    try:
        events = gl.get_merge_request_label_events(mr)
    except gitlab.exceptions.GitlabError as e:
        logging.warning([
            "omm-group",
            "skip-ci-label-events-unavailable",
            gl.project.name,
            mr.iid,
            str(e),
        ])
        return None
    if not isinstance(events, list):
        return None

    stamped: list[tuple[datetime, str]] = []
    for event in events:
        if _event_label_name(event) != OMM_PENDING:
            continue
        action = getattr(event, "action", None)
        created_at = getattr(event, "created_at", None)
        if action not in {"add", "remove"} or not isinstance(created_at, str):
            logging.warning([
                "omm-group",
                "skip-ci-label-events-unparsed",
                gl.project.name,
                mr.iid,
            ])
            return None
        try:
            stamped.append((from_utc_iso_format(created_at), action))
        except TypeError, ValueError:
            logging.warning([
                "omm-group",
                "skip-ci-label-events-unparsed",
                gl.project.name,
                mr.iid,
            ])
            return None
    stamped.sort(key=itemgetter(0))

    intervals: list[tuple[datetime, datetime | None]] = []
    open_start: datetime | None = None
    for when, action in stamped:
        if action == "add":
            if open_start is None:
                open_start = when
        elif open_start is not None:
            intervals.append((open_start, when))
            open_start = None
    if open_start is not None:
        intervals.append((open_start, None))
    return intervals


def _committed_during_label(
    committed_at: datetime,
    intervals: list[tuple[datetime, datetime | None]],
) -> bool:
    for start, end in intervals:
        if committed_at < start:
            continue
        if end is None:
            return True
        # Git commit times are whole seconds; label events keep fractions.
        # A post-remove rebase at 00:10:00.900 is stored as 00:10:00.000.
        # Floor the remove so that second is not treated as still in-window.
        if committed_at < end.replace(microsecond=0):
            return True
    return False


def _sha_commit(
    gl: GitLabApi,
    project_id: int | str,
    sha: str,
    cache: dict[tuple[int | str, str], tuple[str, datetime] | None],
) -> tuple[str, datetime] | None:
    """(committer_email, committed_at) for sha, or None if it cannot be read."""
    key = (project_id, sha)
    if key in cache:
        return cache[key]
    try:
        commit = gl.get_commit(project_id, sha)
        email = getattr(commit, "committer_email", None)
        committed_at = getattr(commit, "committed_date", None)
        if not isinstance(email, str) or not email.strip():
            cache[key] = None
            return None
        if not isinstance(committed_at, str):
            cache[key] = None
            return None
        parsed = (email.strip().lower(), from_utc_iso_format(committed_at))
    except (gitlab.exceptions.GitlabError, TypeError, ValueError) as e:
        logging.warning([
            "omm-group",
            "skip-ci-commit-unavailable",
            project_id,
            sha,
            str(e),
        ])
        cache[key] = None
        return None
    cache[key] = parsed
    return parsed


def _without_skip_ci_bot_pipelines(
    gl: GitLabApi,
    mr: ProjectMergeRequest,
    pipelines: list[Any],
) -> list[Any]:
    """Drop pipelines on bot commits written while omm-pending was on.

    Lookup failure keeps the pipelines. Committer alone is not a drop.
    """
    intervals = _omm_pending_on_intervals(gl, mr)
    if not intervals:
        return pipelines
    emails = _bot_commit_emails(gl)
    if not emails:
        return pipelines

    cache: dict[tuple[int | str, str], tuple[str, datetime] | None] = {}
    kept: list[Any] = []
    dropped: list[str] = []
    for pipeline in pipelines:
        project_id = getattr(pipeline, "project_id", None)
        sha = getattr(pipeline, "sha", None)
        if project_id is None or not isinstance(sha, str):
            kept.append(pipeline)
            continue
        commit = _sha_commit(gl, project_id, sha, cache)
        if commit is None:
            kept.append(pipeline)
            continue
        email, committed_at = commit
        if email in emails and _committed_during_label(committed_at, intervals):
            dropped.append(sha)
            continue
        kept.append(pipeline)
    if dropped:
        logging.info([
            "omm-group",
            "skip-ci-bot-pipeline-ignored",
            gl.project.name,
            mr.iid,
            sorted(set(dropped)),
        ])
    return kept


def _status_requires_wait(status: Any, *, require_success: bool) -> bool:
    """True when this pipeline status must not proceed on leftover SUCCESS."""
    if status == PipelineStatus.SUCCESS:
        return False
    if status in {PipelineStatus.RUNNING, PipelineStatus.PENDING}:
        return require_success
    return True


def _usable_sha_status(pipelines: list[Any], sha: str) -> Any:
    return next(
        (
            getattr(p, "status", None)
            for p in pipelines
            if getattr(p, "sha", None) == sha
            and getattr(p, "status", None) != PipelineStatus.SKIPPED
            and getattr(p, "source", None) != "push"
        ),
        None,
    )


def _prior_revision_requires_wait(
    gl: GitLabApi,
    mr: ProjectMergeRequest,
    pipelines: list[Any],
    *,
    require_success: bool,
) -> bool:
    """Skip-ci tip: judge the newest remaining revision, not leftover SUCCESS.

    Formation rebases the admitted SHA to a skip-ci commit. The skip-ci row is
    dropped, so pipelines[0] can be an older SHA's SUCCESS while the pre-rebase
    CI is still running or has failed. Use commit time, not created_at.
    Git commit times are whole seconds. Different SHAs in that second are not
    ordered, so wait unless every one of them is SUCCESS. The same SHA twice
    is not a tie. Unreadable remaining commits wait: that is not proof the
    prior SHA is green.
    """
    cache: dict[tuple[int | str, str], tuple[str, datetime] | None] = {}
    best_at: datetime | None = None
    best_shas: set[str] = set()
    for pipeline in pipelines:
        sha = getattr(pipeline, "sha", None)
        if not isinstance(sha, str):
            continue
        if getattr(pipeline, "status", None) == PipelineStatus.SKIPPED:
            continue
        if getattr(pipeline, "source", None) == "push":
            continue
        project_id = getattr(pipeline, "project_id", None)
        if project_id is None:
            project_id = getattr(mr, "source_project_id", None)
        if project_id is None:
            return True
        commit = _sha_commit(gl, project_id, sha, cache)
        if commit is None:
            return True
        _email, committed_at = commit
        if best_at is None or committed_at > best_at:
            best_at = committed_at
            best_shas = {sha}
        elif committed_at == best_at:
            best_shas.add(sha)
    if not best_shas:
        return True
    if len(best_shas) == 1:
        return _status_requires_wait(
            _usable_sha_status(pipelines, next(iter(best_shas))),
            require_success=require_success,
        )
    return any(
        _usable_sha_status(pipelines, sha) != PipelineStatus.SUCCESS
        for sha in best_shas
    )


def _bot_head_awaiting_pipeline(
    gl: GitLabApi,
    mr: ProjectMergeRequest,
    pipelines: list[Any],
    *,
    require_success: bool = False,
) -> bool:
    """True when the live head must not proceed on an older SUCCESS.

    SKIPPED rows and source=push shells do not count. Those are placeholders,
    not Jenkins. Caller should pass the usable list (placeholders and in-window
    skip-ci bot pipelines already dropped).

    Decision uses this SHA's newest usable row, not pipelines[0] across SHAs.
    SUCCESS: proceed. FAILED or CANCELED: do not. RUNNING or PENDING: proceed
    for admission (join and wait); block when require_success=True (merge).
    No usable row: wait, unless the head is an in-window skip-ci commit.

    An in-window skip-ci head still waits when the newest remaining revision
    (by commit time) is not SUCCESS. Different SHAs that share that second wait
    unless every one of them is SUCCESS. Leftover SUCCESS on an older SHA must
    not authorize merge while the pre-rebase CI is running or failed.

    If the tip has no usable pipeline and the commit cannot be classified,
    wait. Lookup failure is not proof it is safe to join on older SUCCESS.
    """
    sha = getattr(mr, "sha", None)
    if not isinstance(sha, str):
        return True
    head_status = _usable_sha_status(pipelines, sha)
    if head_status is not None:
        return _status_requires_wait(head_status, require_success=require_success)
    emails = _bot_commit_emails(gl)
    if not emails:
        logging.warning([
            "omm-group",
            "skip-ci-bot-email-unavailable",
            gl.project.name,
            mr.iid,
        ])
        return True
    project_id = getattr(mr, "source_project_id", None)
    if project_id is None:
        return True
    commit = _sha_commit(gl, project_id, sha, {})
    if commit is None:
        return True
    email, committed_at = commit
    if email not in emails:
        return False
    intervals = _omm_pending_on_intervals(gl, mr)
    if not (intervals and _committed_during_label(committed_at, intervals)):
        return True
    return _prior_revision_requires_wait(
        gl, mr, pipelines, require_success=require_success
    )


def form_omm_group(
    gl: GitLabApi,
    merge_requests: list[dict[str, Any]],
    merged_labels: set[str],
) -> list[ProjectMergeRequest]:
    """Select non-overlapping candidates from the queue for the OMM group.

    Only MRs that are eligible (have tenant labels), don't overlap with
    already-merged labels, and have an active pipeline are considered.

    Note: this makes one get_merge_request_pipelines API call per candidate,
    proportional to queue length. Acceptable because it runs at most once per
    reconcile loop after the first merge, and once more during expansion.
    """
    candidates: list[ProjectMergeRequest] = []
    group_labels = set(merged_labels)

    for merge_request in merge_requests:
        mr: ProjectMergeRequest = merge_request["mr"]
        if merge_request["error"]:
            continue
        if not is_eligible_for_optimistic_merge(mr):
            continue
        mr_labels = get_tenant_labels(mr)
        if has_overlapping_labels(mr_labels, group_labels):
            continue
        pipelines = gl.get_merge_request_pipelines(mr)
        visible = [
            p
            for p in pipelines
            if not (p.status == PipelineStatus.SKIPPED or p.source == "push")
        ]
        visible = _without_skip_ci_bot_pipelines(gl, mr, visible)
        if not visible:
            continue
        if visible[0].status not in {
            PipelineStatus.RUNNING,
            PipelineStatus.PENDING,
            PipelineStatus.SUCCESS,
        }:
            continue
        try:
            fresh = gl.get_merge_request(mr.iid, include_rebase_in_progress=True)
        except gitlab.exceptions.GitlabError as e:
            logging.warning([
                "omm-group",
                "skip-admission-mr-unavailable",
                gl.project.name,
                mr.iid,
                str(e),
            ])
            continue
        if getattr(fresh, "rebase_in_progress", None) is True:
            logging.info([
                "omm-group",
                "skip-admission-rebase-in-progress",
                gl.project.name,
                mr.iid,
            ])
            continue
        if _bot_head_awaiting_pipeline(gl, fresh, visible):
            logging.info([
                "omm-group",
                "skip-admission-bot-head-awaiting-pipeline",
                gl.project.name,
                mr.iid,
                fresh.sha,
            ])
            continue
        candidates.append(mr)
        group_labels.update(mr_labels)

    return candidates


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


def _is_omm_window_open(lead: ProjectMergeRequest, max_interval: timedelta) -> bool:
    """Check if the OMM group window is still open based on lead's merged_at."""
    merged_at = from_utc_iso_format(lead.merged_at)
    return utc_now() - merged_at < max_interval


def _check_post_merge_ci(gl: GitLabApi, lead: ProjectMergeRequest) -> bool:
    """Return True if post-merge CI is healthy (not failed).

    Only considers pipelines created after the lead was merged so that
    a stale pre-merge failure doesn't cancel a new OMM group.
    """
    merged_at = from_utc_iso_format(lead.merged_at)
    pipelines = gl.project.pipelines.list(
        ref=lead.target_branch,
        order_by="id",
        sort="desc",
        per_page=1,
        get_all=False,
    )
    for pipeline in pipelines:
        if from_utc_iso_format(pipeline.created_at) < merged_at:
            break
        return pipeline.status != PipelineStatus.FAILED
    return True


def _check_target_branch_integrity(
    gl: GitLabApi,
    lead: ProjectMergeRequest,
    lead_sha: str,
) -> bool:
    """Return True if the target branch is safe to continue merging onto.

    Detects external merges by checking whether the current branch HEAD
    corresponds to a known OMM merge commit. Uses the detail API to refresh
    merge_commit_sha and avoid stale list-API values.
    """
    current_head = gl.project.branches.get(lead.target_branch).commit["id"]
    if current_head == lead_sha:
        return True

    result = cast(
        "dict",
        gl.project.repository_compare(current_head, lead_sha),
    )
    if len(result["commits"]) > 0:
        logging.warning([
            "omm-group",
            "head-diverged",
            gl.project.name,
            "invalidating",
        ])
        return False

    merged_omm = gl.project.mergerequests.list(
        state=MRState.MERGED,
        labels=[OMM_PENDING],
        target_branch=lead.target_branch,
        get_all=True,
    )
    omm_shas: set[str] = set()
    for mr in merged_omm:
        fresh = gl.get_merge_request(mr.iid)
        if fresh.merge_commit_sha:
            omm_shas.add(fresh.merge_commit_sha)
        if fresh.squash_commit_sha:
            omm_shas.add(fresh.squash_commit_sha)

    if current_head in omm_shas:
        return True

    logging.warning([
        "omm-group",
        "external-merge-detected",
        gl.project.name,
        f"HEAD {current_head[:8]} not in OMM SHAs",
    ])
    return False


@dataclass
class _MemberResult:
    merged: bool = False
    active: bool = False


def _process_omm_member(
    dry_run: bool,
    gl: GitLabApi,
    mr: ProjectMergeRequest,
    app_sre_usernames: AbstractSet[str],
    pipeline_timeout: int | None,
) -> _MemberResult:
    """Process a single OMM pending member. Returns merge/active state."""
    error_labels = ERROR_LABELS.intersection(mr.labels)
    if error_labels:
        logging.info([
            "omm-group",
            "eject-error-label",
            gl.project.name,
            mr.iid,
            sorted(error_labels),
        ])
        if not dry_run:
            gl.remove_label(mr, OMM_PENDING)
        optimistic_merge_rejected.labels(
            project_id=mr.target_project_id,
            reason="error_label",
        ).inc()
        return _MemberResult()

    hold_labels = set(HOLD_LABELS).intersection(mr.labels)
    if hold_labels:
        logging.info([
            "omm-group",
            "eject-hold-label",
            gl.project.name,
            mr.iid,
            sorted(hold_labels),
        ])
        if not dry_run:
            gl.remove_label(mr, OMM_PENDING)
        optimistic_merge_rejected.labels(
            project_id=mr.target_project_id,
            reason="hold_label",
        ).inc()
        return _MemberResult()

    pipelines = gl.get_merge_request_pipelines(mr)

    if pipeline_timeout is not None and pipelines:
        timed_out = get_timed_out_pipelines(pipelines, pipeline_timeout)
        if timed_out:
            clean_pipelines(
                dry_run=dry_run,
                gl=gl,
                fork_project_id=mr.source_project_id,
                pipelines=timed_out,
            )

    # Filter pipelines that carry no CI signal:
    # - SKIPPED: placeholder from skip_ci rebase
    # - PUSH: empty 0-job shells from skip_ci rebase (real CI is source=external)
    # - bot commits written while omm-pending was on: post-19.2 skip-ci Jenkins
    pipelines = [
        p
        for p in pipelines
        if not (p.status == PipelineStatus.SKIPPED or p.source == "push")
    ]
    pipelines = _without_skip_ci_bot_pipelines(gl, mr, pipelines)

    fresh_mr = gl.get_merge_request(mr.iid)
    try:
        mr_is_rebased = is_rebased(fresh_mr, gl)
    except gitlab.exceptions.GitlabGetError as e:
        if e.response_code != 404:
            raise
        logging.warning([
            "omm-group",
            "ref-not-found",
            gl.project.name,
            mr.iid,
            fresh_mr.sha,
            str(e),
        ])
        if not dry_run:
            gl.remove_label(mr, OMM_PENDING)
        optimistic_merge_rejected.labels(
            project_id=mr.target_project_id,
            reason="ref_not_found",
        ).inc()
        return _MemberResult()

    if not pipelines:
        if mr_is_rebased:
            logging.info([
                "omm-group",
                "no-pipelines-rebased",
                gl.project.name,
                mr.iid,
            ])
            return _MemberResult(active=True)
        return _MemberResult()

    latest_status = pipelines[0].status

    if latest_status in {PipelineStatus.FAILED, PipelineStatus.CANCELED}:
        logging.info([
            "omm-group",
            "eject-failed",
            gl.project.name,
            mr.iid,
            latest_status,
        ])
        if not dry_run:
            gl.remove_label(mr, OMM_PENDING)
        optimistic_merge_rejected.labels(
            project_id=mr.target_project_id,
            reason=f"pipeline_{getattr(latest_status, 'value', latest_status)}",
        ).inc()
        return _MemberResult()

    if latest_status in {PipelineStatus.RUNNING, PipelineStatus.PENDING}:
        logging.info([
            "omm-group",
            "waiting-pipeline",
            gl.project.name,
            mr.iid,
            latest_status,
            "rebased" if mr_is_rebased else "not-rebased",
        ])
        return _MemberResult(active=True)

    if latest_status != PipelineStatus.SUCCESS:
        logging.info([
            "omm-group",
            "unhandled-status",
            gl.project.name,
            mr.iid,
            latest_status,
            "rebased" if mr_is_rebased else "not-rebased",
        ])
        return _MemberResult(active=mr_is_rebased)

    # Same tip check as serial merge. In-window skip-ci may still merge on
    # older SUCCESS. A failed or untested post-label bot head must not.
    if _bot_head_awaiting_pipeline(gl, fresh_mr, pipelines, require_success=True):
        logging.info([
            "omm-group",
            "bot-head-awaiting-pipeline",
            gl.project.name,
            mr.iid,
            getattr(fresh_mr, "sha", None),
        ])
        return _MemberResult(active=True)

    # --- SUCCESS: the only path that differs on rebased state ---
    if mr_is_rebased:
        logging.info(["omm-group", "merge", gl.project.name, mr.iid])
        if not dry_run:
            try:
                squash = (gl.project.squash_option == SQUASH_OPTION_ALWAYS) or mr.squash
                mr.merge(squash=squash)
                labels = mr.labels
                merged_merge_requests.labels(
                    project_id=mr.target_project_id,
                    self_service=SELF_SERVICEABLE in labels,
                    auto_merge=AUTO_MERGE in labels,
                    app_sre=mr.author["username"] in app_sre_usernames,
                    onboarding=ONBOARDING in labels,
                ).inc()
                optimistic_merges.labels(project_id=mr.target_project_id).inc()
                approval_info = _get_approval_info(gl, mr)
                if approval_info:
                    priority, approved_at = approval_info
                    time_to_merge.labels(
                        project_id=mr.target_project_id, priority=priority
                    ).observe(calculate_time_since_approval(approved_at))
            except gitlab.exceptions.GitlabMRClosedError as e:
                logging.error(f"unable to merge {mr.iid}: {e}")
                gl.add_label_to_merge_request(mr, MERGE_ERROR)
                optimistic_merge_rejected.labels(
                    project_id=mr.target_project_id, reason="merge_rejected"
                ).inc()
                return _MemberResult()
        return _MemberResult(merged=True)

    # Not rebased + SUCCESS: skip-ci rebase to bring MR up to date
    logging.info([
        "omm-group",
        "skip-ci-rebase",
        gl.project.name,
        mr.iid,
    ])
    if not dry_run:
        try:
            mr.rebase(skip_ci=True)
        except gitlab.exceptions.GitlabMRRebaseError as e:
            logging.warning([
                "omm-group",
                "skip-ci-rebase-failed",
                gl.project.name,
                mr.iid,
                str(e),
            ])
            gl.remove_label(mr, OMM_PENDING)
            optimistic_merge_rejected.labels(
                project_id=mr.target_project_id,
                reason="skip_ci_rebase_conflict",
            ).inc()
            return _MemberResult()
    return _MemberResult(active=True)


def process_omm_group(
    dry_run: bool,
    gl: GitLabApi,
    lead: ProjectMergeRequest,
    app_sre_usernames: AbstractSet[str],
    pipeline_timeout: int | None = None,
    merge_limit: int = 8,
    merge_requests: list[dict[str, Any]] | None = None,
) -> int:
    """Process an active OMM group. Returns number of merges performed.

    Single-pass: check window, verify post-merge CI, eject overlapping
    pending members, process each remaining member (merge if ready, eject
    if failed), then expand with new non-overlapping candidates.
    Non-blocking.

    Enforces ``merge_limit`` — when reached the group is cleared so the
    next loop starts fresh with a serial merge and re-evaluation.
    """

    max_interval = get_omm_max_interval()

    if not _is_omm_window_open(lead, max_interval):
        logging.info(["omm-group", "window-expired", gl.project.name])
        clear_omm_group(dry_run, gl, lead=lead)
        return 0

    if not _check_post_merge_ci(gl, lead):
        logging.warning([
            "omm-group",
            "post-merge-ci-failed",
            gl.project.name,
            "cancelling group",
        ])
        clear_omm_group(dry_run, gl, lead=lead)
        return 0

    lead_sha = lead.merge_commit_sha or lead.squash_commit_sha
    if not lead_sha:
        logging.warning([
            "omm-group",
            "lead-missing-sha",
            gl.project.name,
            lead.iid,
            "will retry next loop",
        ])
        return 0

    # Runs once here rather than per-member: is_rebased() in _process_omm_member
    # fetches the live HEAD each call, so a mid-loop external merge still prevents
    # the next member from merging (it won't be rebased against the new HEAD).
    if not _check_target_branch_integrity(gl, lead, lead_sha):
        clear_omm_group(dry_run, gl, lead=lead)
        return 0

    pending = get_omm_pending_mrs(gl)
    if not pending:
        logging.info(["omm-group", "no-pending-members", gl.project.name])
        clear_omm_group(dry_run, gl, lead=lead, pending=pending)
        return 0

    seen_labels: set[str] = set(get_tenant_labels(lead))
    kept: list[ProjectMergeRequest] = []
    for mr in pending:
        mr_labels = get_tenant_labels(mr)
        if has_overlapping_labels(mr_labels, seen_labels):
            logging.info(["omm-group", "eject-overlap", gl.project.name, mr.iid])
            if not dry_run:
                gl.remove_label(mr, OMM_PENDING)
            continue
        seen_labels.update(mr_labels)
        kept.append(mr)
    pending = kept

    merges = 0
    any_active = False

    for mr in pending:
        r = _process_omm_member(dry_run, gl, mr, app_sre_usernames, pipeline_timeout)
        if r.merged:
            merges += 1
            if merges >= merge_limit:
                logging.info([
                    "omm-group",
                    "merge-limit-reached",
                    gl.project.name,
                    f"limit={merge_limit}",
                ])
                clear_omm_group(dry_run, gl, lead=lead, pending=pending)
                return merges
        any_active |= r.active

    queue = merge_requests or []
    pending_iids = {mr.iid for mr in pending}
    group_labels = set(get_tenant_labels(lead))
    for mr in pending:
        group_labels.update(get_tenant_labels(mr))
    expansion_queue = [m for m in queue if m["mr"].iid not in pending_iids]
    new_candidates = form_omm_group(gl, expansion_queue, group_labels)
    if new_candidates:
        logging.info([
            "omm-group",
            "expanded",
            gl.project.name,
            f"added={len(new_candidates)}",
            f"group_size={len(pending) + len(new_candidates)}",
        ])
        retained = apply_omm_pending(dry_run, gl, new_candidates)
        if retained:
            omm_group_expanded.labels(project_id=gl.project.id).inc(len(retained))
            any_active = True

    if not any_active:
        logging.info(["omm-group", "adaptive-close", gl.project.name])
        clear_omm_group(dry_run, gl, lead=lead)

    return merges
