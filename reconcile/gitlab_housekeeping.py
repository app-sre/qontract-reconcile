import logging

from datetime import datetime, timedelta
from operator import itemgetter
from typing import Dict, Iterable, List, Optional, Union

import gitlab

from gitlab.v4.objects import ProjectMergeRequest, ProjectIssue
from sretoolbox.utils import retry

from reconcile import queries

from reconcile.utils.gitlab_api import GitLabApi, MRState, MRStatus
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
    SAAS_FILE_UPDATE,
    SELF_SERVICEABLE,
)

MERGE_LABELS_PRIORITY = [APPROVED, AUTO_MERGE, LGTM]
HOLD_LABELS = [
    AWAITING_APPROVAL,
    BLOCKED_BOT_ACCESS,
    CHANGES_REQUESTED,
    HOLD,
    DO_NOT_MERGE_HOLD,
    DO_NOT_MERGE_PENDING_REVIEW,
]

QONTRACT_INTEGRATION = "gitlab-housekeeping"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def get_timed_out_pipelines(
    pipelines: List[Dict], pipeline_timeout: int = 60
) -> List[Dict]:
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
    pipelines: List[Dict],
) -> None:
    if not dry_run:
        gl_piplelines = GitLabApi(
            gl_instance, project_id=gl_project_id, settings=gl_settings
        ).project.pipelines

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
    logging.info(["close_item", gl.project.name, item_type, item.attributes.get("iid")])
    if enable_closing:
        if not dry_run:
            gl.close(item)
    else:
        warning_message = (
            "'close_item' action is not enabled. "
            + "Please run the integration manually "
            + "with the '--enable-deletion' flag."
        )
        logging.warning(warning_message)


def handle_stale_items(dry_run, gl, days_interval, enable_closing, item_type):
    LABEL = "stale"

    if item_type == "issue":
        items = gl.get_issues(state=MRState.OPENED)
    elif item_type == "merge-request":
        items = gl.get_merge_requests(state=MRState.OPENED)

    now = datetime.utcnow()
    for item in items:
        item_iid = item.attributes.get("iid")
        item_labels = get_labels(item, gl)
        if AUTO_MERGE in item_labels:
            if item.merge_status == MRStatus.UNCHECKED:
                # this call triggers a status recheck
                item = gl.get_merge_request(item_iid)
            if item.merge_status == MRStatus.CANNOT_BE_MERGED:
                close_item(dry_run, gl, enable_closing, item_type, item)
        notes = item.notes.list()
        note_dates = [
            datetime.strptime(note.attributes.get("updated_at"), DATE_FORMAT)
            for note in notes
        ]
        update_date = max(d for d in note_dates) if note_dates else now

        # if item is over days_interval
        current_interval = now.date() - update_date.date()
        if current_interval > timedelta(days=days_interval):
            # if item does not have 'stale' label - add it
            if LABEL not in item_labels:
                logging.info(["add_label", gl.project.name, item_type, item_iid, LABEL])
                if not dry_run:
                    gl.add_label(item, item_type, LABEL)
            # if item has 'stale' label - close it
            else:
                close_item(dry_run, gl, enable_closing, item_type, item)
        # if item is under days_interval
        else:
            if LABEL not in item_labels:
                continue

            # if item has 'stale' label - check the notes
            cancel_notes = [
                n
                for n in notes
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
                    gl.remove_label(item, item_type, LABEL)


def is_good_to_merge(labels):
    return any(m in MERGE_LABELS_PRIORITY for m in labels) and not any(
        b in HOLD_LABELS for b in labels
    )


def is_rebased(mr, gl: GitLabApi) -> bool:
    target_branch = mr.target_branch
    head = gl.project.commits.list(ref_name=target_branch)[0].id
    result = gl.project.repository_compare(mr.sha, head)
    return len(result["commits"]) == 0


def get_labels(mr: ProjectMergeRequest, gl: GitLabApi) -> list[str]:
    labels = mr.attributes.get("labels")
    if not labels:
        # Sometimes the label attribute is empty but shouldn't. Try it again by fetching this MR separately
        labels = gl.get_merge_request_labels(mr.iid)
    return labels


def get_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    users_allowed_to_label: Optional[Iterable[str]] = None,
) -> list:
    mrs = gl.get_merge_requests(state=MRState.OPENED)
    results = []
    for mr in mrs:
        if mr.merge_status in [
            MRStatus.CANNOT_BE_MERGED,
            MRStatus.CANNOT_BE_MERGED_RECHECK,
        ]:
            continue
        if mr.work_in_progress:
            continue
        if len(mr.commits()) == 0:
            continue

        labels = get_labels(mr, gl)
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
                gl.remove_label_from_merge_request(mr.iid, LGTM)
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
                else:
                    # label added by an authorized user, so don't delete it
                    labels_by_authorized_users.add(label_name)

                if label_name in MERGE_LABELS_PRIORITY and not approval_found:
                    approval_found = True
                    approved_at = label.created_at
                    approved_by = added_by

        for bad_label in labels_by_unauthorized_users - labels_by_authorized_users:
            if bad_label not in labels:
                continue
            logging.warning(
                f"[{gl.project.name}/{mr.iid}] someone added a label who "
                f"isn't allowed. removing label {bad_label}"
            )
            # Remove bad_label from the cached labels list. Otherwise, we may face a caching bug
            labels.remove(bad_label)
            if not dry_run:
                gl.remove_label_from_merge_request(mr.iid, bad_label)

        if not is_good_to_merge(labels):
            continue

        label_priotiry = min(
            MERGE_LABELS_PRIORITY.index(merge_label)
            for merge_label in MERGE_LABELS_PRIORITY
            if merge_label in labels
        )

        item = {
            "mr": mr,
            "labels": labels,
            "label_priority": label_priotiry,
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


@retry(max_attempts=10)
def merge_merge_requests(
    dry_run,
    gl,
    merge_limit,
    rebase,
    pipeline_timeout=None,
    insist=False,
    wait_for_pipeline=False,
    gl_instance=None,
    gl_settings=None,
    users_allowed_to_label=None,
):
    merges = 0
    merge_requests = [
        item["mr"] for item in get_merge_requests(dry_run, gl, users_allowed_to_label)
    ]
    for mr in merge_requests:
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
                    raise Exception(f"insisting on {mr.iid}")
                else:
                    continue

        last_pipeline_result = pipelines[0]["status"]
        if last_pipeline_result != "success":
            continue

        logging.info(["merge", gl.project.name, mr.iid])
        if not dry_run and merges < merge_limit:
            try:
                mr.merge()
                if rebase:
                    return
                merges += 1
            except gitlab.exceptions.GitlabMRClosedError as e:
                logging.error("unable to merge {}: {}".format(mr.iid, e))


def run(dry_run, wait_for_pipeline):
    default_days_interval = 15
    default_limit = 8
    default_enable_closing = False
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    repos = queries.get_repos_gitlab_housekeeping(server=instance["url"])

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
        gl = GitLabApi(instance, project_url=project_url, settings=settings)

        handle_stale_items(dry_run, gl, days_interval, enable_closing, "issue")
        handle_stale_items(dry_run, gl, days_interval, enable_closing, "merge-request")
        rebase = hk.get("rebase")
        try:
            merge_merge_requests(
                dry_run,
                gl,
                limit,
                rebase,
                pipeline_timeout,
                insist=True,
                wait_for_pipeline=wait_for_pipeline,
                gl_instance=instance,
                gl_settings=settings,
                users_allowed_to_label=users_allowed_to_label,
            )
        except Exception:
            merge_merge_requests(
                dry_run,
                gl,
                limit,
                rebase,
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
