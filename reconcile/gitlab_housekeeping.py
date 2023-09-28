import logging
from collections.abc import (
    Iterable,
    Set,
)
from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
)
from operator import itemgetter
from typing import (
    Any,
    Optional,
    Union,
)

import gitlab
from gitlab.v4.objects import (
    ProjectIssue,
    ProjectMergeRequest,
)
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
)
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.change_owners.change_types import ChangeTypePriority
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
    NEEDS_REBASE,
    ONBOARDING,
    SAAS_FILE_UPDATE,
    SELF_SERVICEABLE,
    prioritized_approval_label,
)

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

QONTRACT_INTEGRATION = "gitlab-housekeeping"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


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
    time_since_approval = datetime.utcnow() - datetime.strptime(
        approved_at, DATE_FORMAT
    )
    return time_since_approval.total_seconds() / 60


def get_timed_out_pipelines(
    pipelines: list[dict], pipeline_timeout: int = 60
) -> list[dict]:
    now = datetime.utcnow()

    pending_pipelines = [p for p in pipelines if p["status"] in ["pending", "running"]]

    if not pending_pipelines:
        return []

    timed_out_pipelines = []

    for p in pending_pipelines:
        update_time = datetime.strptime(p["updated_at"], DATE_FORMAT)

        elapsed = (now - update_time).total_seconds()

        # pipeline_timeout converted in seconds
        if elapsed > pipeline_timeout * 60:
            timed_out_pipelines.append(p)

    return timed_out_pipelines


def clean_pipelines(
    dry_run: bool,
    gl_instance: str,
    gl_project_id: int,
    gl_settings: str,
    pipelines: list[dict],
) -> None:
    if not dry_run:
        with GitLabApi(
            gl_instance, project_id=gl_project_id, settings=gl_settings
        ) as gl:
            gl_piplelines = gl.project.pipelines

    for p in pipelines:
        logging.info(["canceling", p["web_url"]])
        if not dry_run:
            try:
                gl_piplelines.get(p["id"]).cancel()
            except gitlab.exceptions.GitlabPipelineCancelError as err:
                logging.error(
                    f'unable to cancel {p["web_url"]} - '
                    f"error message {err.error_message}"
                )


def close_item(
    dry_run: bool,
    gl: GitLabApi,
    enable_closing: bool,
    item_type: str,
    item: Union[ProjectIssue, ProjectMergeRequest],
):
    if enable_closing:
        logging.info(
            [
                "close_item",
                gl.project.name,
                item_type,
                item.attributes.get("iid"),
            ]
        )
        if not dry_run:
            gl.close(item)
    else:
        logging.debug(
            [
                "'enable_closing' is not enabled to close item",
                gl.project.name,
                item_type,
                item.attributes.get("iid"),
            ]
        )


def handle_stale_items(
    dry_run,
    gl,
    days_interval,
    enable_closing,
    items,
    item_type,
):
    LABEL = "stale"

    now = datetime.utcnow()
    for item in items:
        item_iid = item.attributes.get("iid")
        if AUTO_MERGE in item.labels:
            if item.merge_status == MRStatus.UNCHECKED:
                # this call triggers a status recheck
                item = gl.get_merge_request(item_iid)
            if item.merge_status == MRStatus.CANNOT_BE_MERGED:
                close_item(dry_run, gl, enable_closing, item_type, item)
        update_date = datetime.strptime(item.attributes.get("updated_at"), DATE_FORMAT)

        # if item is over days_interval
        current_interval = now.date() - update_date.date()
        if current_interval > timedelta(days=days_interval):
            # if item does not have 'stale' label - add it
            if LABEL not in item.labels:
                logging.info(["add_label", gl.project.name, item_type, item_iid, LABEL])
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
            cancel_notes = [
                n
                for n in item.notes.list()
                if n.attributes.get("body") == "/{} cancel".format(LABEL)
            ]
            if not cancel_notes:
                continue

            cancel_notes_dates = [
                datetime.strptime(note.attributes.get("updated_at"), DATE_FORMAT)
                for note in cancel_notes
            ]
            latest_cancel_note_date = max(d for d in cancel_notes_dates)
            # if the latest cancel note is under
            # days_interval - remove 'stale' label
            current_interval = now.date() - latest_cancel_note_date.date()
            if current_interval <= timedelta(days=days_interval):
                logging.info(
                    ["remove_label", gl.project.name, item_type, item_iid, LABEL]
                )
                if not dry_run:
                    gl.remove_label(item, LABEL)


def is_good_to_merge(labels):
    return any(m in MERGE_LABELS_PRIORITY for m in labels) and not any(
        b in HOLD_LABELS for b in labels
    )


def is_rebased(mr, gl: GitLabApi) -> bool:
    target_branch = mr.target_branch
    head = gl.project.commits.list(ref_name=target_branch, per_page=1)[0].id
    result = gl.project.repository_compare(mr.sha, head)
    return len(result["commits"]) == 0


def get_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    users_allowed_to_label: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    mrs = gl.get_merge_requests(state=MRState.OPENED)
    return preprocess_merge_requests(
        dry_run=dry_run,
        gl=gl,
        project_merge_requests=mrs,
        users_allowed_to_label=users_allowed_to_label,
    )


def preprocess_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    users_allowed_to_label: Optional[Iterable[str]] = None,
) -> list[dict[str, Any]]:
    results = []
    for mr in project_merge_requests:
        if mr.merge_status in [
            MRStatus.CANNOT_BE_MERGED,
            MRStatus.CANNOT_BE_MERGED_RECHECK,
        ]:
            continue
        if mr.work_in_progress:
            continue
        if len(mr.commits()) == 0:
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
        }
        results.append(item)

    results.sort(key=itemgetter("label_priority", "approved_at"))

    return results


def rebase_merge_requests(
    dry_run,
    gl,
    rebase_limit,
    pipeline_timeout=None,
    wait_for_pipeline=False,
    gl_instance=None,
    gl_settings=None,
    users_allowed_to_label=None,
):
    rebases = 0
    merge_requests = [
        item["mr"] for item in get_merge_requests(dry_run, gl, users_allowed_to_label)
    ]
    for mr in merge_requests:
        if is_rebased(mr, gl):
            continue

        pipelines = gl.get_merge_request_pipelines(mr)

        # If pipeline_timeout is None no pipeline will be canceled
        if pipeline_timeout is not None:
            timed_out_pipelines = get_timed_out_pipelines(pipelines, pipeline_timeout)
            if timed_out_pipelines:
                clean_pipelines(
                    dry_run,
                    gl_instance,
                    mr.source_project_id,
                    gl_settings,
                    timed_out_pipelines,
                )

        if wait_for_pipeline:
            if not pipelines:
                continue
            # possible statuses:
            # running, pending, success, failed, canceled, skipped
            running_pipelines = [p for p in pipelines if p["status"] == "running"]
            if running_pipelines:
                continue

        if rebases < rebase_limit:
            try:
                logging.info(["rebase", gl.project.name, mr.iid])
                if not dry_run:
                    mr.rebase()
                    rebases += 1
                    rebased_merge_requests.labels(mr.target_project_id).inc()
            except gitlab.exceptions.GitlabMRRebaseError as e:
                logging.error("unable to rebase {}: {}".format(mr.iid, e))
        else:
            logging.info(
                [
                    "rebase",
                    gl.project.name,
                    mr.iid,
                    "rebase limit reached for this reconcile loop. will try next time",
                ]
            )


# TODO: this retry is catching all exceptions, which isn't good. _log_exceptions is
# being added so we can track whether it's catching anything other than what appears to
# be the intended case of retrying with "insist". Once we have some additional data,
# we can change this to retry on a small set of exceptions including
# InsistOnPipelineException.


@retry(max_attempts=10, hook=_log_exception)
def merge_merge_requests(
    dry_run,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    reload_toggle: ReloadToggle,
    merge_limit,
    rebase,
    app_sre_usernames: Set[str],
    pipeline_timeout=None,
    insist=False,
    wait_for_pipeline=False,
    gl_instance=None,
    gl_settings=None,
    users_allowed_to_label=None,
):
    merges = 0
    if reload_toggle.reload:
        project_merge_requests = gl.get_merge_requests(state=MRState.OPENED)
    merge_requests = preprocess_merge_requests(
        dry_run, gl, project_merge_requests, users_allowed_to_label
    )
    merge_requests_waiting.labels(gl.project.id).set(len(merge_requests))

    for merge_request in merge_requests:
        mr: ProjectMergeRequest = merge_request["mr"]
        if rebase and not is_rebased(mr, gl):
            continue

        pipelines = gl.get_merge_request_pipelines(mr)
        if not pipelines:
            continue

        # If pipeline_timeout is None no pipeline will be canceled
        if pipeline_timeout is not None:
            timed_out_pipelines = get_timed_out_pipelines(pipelines, pipeline_timeout)
            if timed_out_pipelines:
                clean_pipelines(
                    dry_run,
                    gl_instance,
                    mr.source_project_id,
                    gl_settings,
                    timed_out_pipelines,
                )

        if wait_for_pipeline:
            # possible statuses:
            # running, pending, success, failed, canceled, skipped
            running_pipelines = [p for p in pipelines if p["status"] == "running"]
            if running_pipelines:
                if insist:
                    # This raise causes the method to restart due to the usage of
                    # retry(). The purpose of this is to wait for the pipeline to
                    # finish. This will cause merge requests to be queried again, which
                    # for now is being considered a feature because a higher priority
                    # merge request could have become available since we've been waiting
                    # for this pipeline to complete.
                    reload_toggle.reload = True
                    raise InsistOnPipelineError(
                        f"Pipelines for merge request in project '{gl.project.name}' have not completed yet: {mr.iid}"
                    )
                continue

        last_pipeline_result = pipelines[0]["status"]
        if last_pipeline_result != "success":
            continue

        logging.info(["merge", gl.project.name, mr.iid])
        if not dry_run and merges < merge_limit:
            try:
                mr.merge()
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
                if rebase:
                    # other merge requests need to be rebased first after this one merged, so terminate
                    return
                merges += 1
            except gitlab.exceptions.GitlabMRClosedError as e:
                logging.error("unable to merge {}: {}".format(mr.iid, e))


def get_app_sre_usernames(gl: GitLabApi) -> set[str]:
    return {u.username for u in gl.get_app_sre_group_users()}


def run(dry_run, wait_for_pipeline):
    default_days_interval = 15
    default_limit = 8
    default_enable_closing = False
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    repos = queries.get_repos_gitlab_housekeeping(server=instance["url"])
    app_sre_usernames: Set[str] = set()

    for repo in repos:
        hk = repo["housekeeping"]
        project_url = repo["url"]
        days_interval = hk.get("days_interval") or default_days_interval
        enable_closing = hk.get("enable_closing") or default_enable_closing
        limit = hk.get("limit") or default_limit
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
            reload_toggle = ReloadToggle(reload=False)
            rebase = hk.get("rebase")
            try:
                merge_merge_requests(
                    dry_run,
                    gl,
                    project_merge_requests,
                    reload_toggle,
                    limit,
                    rebase,
                    app_sre_usernames,
                    pipeline_timeout,
                    insist=True,
                    wait_for_pipeline=wait_for_pipeline,
                    gl_instance=instance,
                    gl_settings=settings,
                    users_allowed_to_label=users_allowed_to_label,
                )
            except Exception:
                logging.error(
                    "All retries failed, trying to rerun merge_merge_requests() again."
                )
                merge_merge_requests(
                    dry_run,
                    gl,
                    project_merge_requests,
                    reload_toggle,
                    limit,
                    rebase,
                    app_sre_usernames,
                    pipeline_timeout,
                    wait_for_pipeline=wait_for_pipeline,
                    gl_instance=instance,
                    gl_settings=settings,
                    users_allowed_to_label=users_allowed_to_label,
                )
            if rebase:
                rebase_merge_requests(
                    dry_run,
                    gl,
                    limit,
                    pipeline_timeout=pipeline_timeout,
                    wait_for_pipeline=wait_for_pipeline,
                    gl_instance=instance,
                    gl_settings=settings,
                    users_allowed_to_label=users_allowed_to_label,
                )
