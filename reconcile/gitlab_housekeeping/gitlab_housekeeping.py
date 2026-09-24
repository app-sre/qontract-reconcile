from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import (
    datetime,
    timedelta,
)
from typing import TYPE_CHECKING

import gitlab
from gitlab.const import PipelineStatus
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.gitlab_housekeeping.healthcheck import run_error_healthcheck
from reconcile.gitlab_housekeeping.helpers import (
    SQUASH_OPTION_ALWAYS,
    calculate_time_since_approval,
    clean_pipelines,
    get_timed_out_pipelines,
    gitlab_token_expiration,
    is_rebased,
    merge_batch_size_histogram,
    merge_requests_error,
    merge_requests_waiting,
    merged_merge_requests,
    time_to_merge,
)
from reconcile.gitlab_housekeeping.labels import (
    get_tenant_labels,
    is_eligible_for_optimistic_merge,
)
from reconcile.gitlab_housekeeping.omm import (
    apply_omm_group_lead,
    apply_omm_pending,
    clear_omm_group,
    form_omm_group,
    get_omm_group_lead,
    get_omm_pending_mrs,
    process_omm_group,
)
from reconcile.gitlab_housekeeping.queue import preprocess_merge_requests
from reconcile.gitlab_housekeeping.rebase import (
    RebaseStrategy,
    get_rebase_strategy,
    rebase_merge_requests,
)
from reconcile.utils.datetime_util import ensure_utc, from_utc_iso_format, utc_now
from reconcile.utils.gitlab_api import (
    GitLabApi,
    MRState,
    MRStatus,
)
from reconcile.utils.mr.labels import (
    AUTO_MERGE,
    MERGE_ERROR,
    ONBOARDING,
    SELF_SERVICEABLE,
)
from reconcile.utils.sharding import is_in_shard
from reconcile.utils.state import State, init_state

if TYPE_CHECKING:
    from collections.abc import (
        Iterable,
    )
    from collections.abc import (
        Set as AbstractSet,
    )

    from gitlab.v4.objects import (
        ProjectIssue,
        ProjectMergeRequest,
        ProjectMergeRequestPipeline,
    )

QONTRACT_INTEGRATION = "gitlab-housekeeping"
EXPIRATION_DATE_FORMAT = "%Y-%m-%d"


class InsistOnPipelineError(Exception):
    """Exception used to retry a merge when the pipeline isn't yet complete."""


@dataclass
class ReloadToggle:
    """A class to toggle the reload of merge requests."""

    reload: bool = False


def _log_exception(ex: Exception) -> None:
    logging.info("Retrying - %s: %s", type(ex).__name__, ex)


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
    LABEL = "stale"  # ruff: ignore[non-lowercase-variable-in-function]

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
    *,
    pipeline_cache: dict[int, list[ProjectMergeRequestPipeline]],
) -> None:
    if reload_toggle.reload:
        project_merge_requests = gl.get_merge_requests(state=MRState.OPENED)
        pipeline_cache.clear()  # in-place; caller holds this dict across insist retries
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

    # --- OMM group cleanup when feature is disabled ---
    # If the Unleash variant was changed away from active-cap-multi-merge
    # while a group was active, clean up orphaned labels.
    if not multi_merge and rebase:
        lead = get_omm_group_lead(gl)
        if lead:
            logging.info(["omm-group", "feature-disabled-cleanup", gl.project.name])
            clear_omm_group(dry_run, gl, lead=lead)

    # --- Active group path ---
    # Early return: insist/retry semantics do not apply here — the group
    # model is non-blocking and tolerates running pipelines without retrying.
    if multi_merge and rebase:
        lead = get_omm_group_lead(gl)
        if lead:
            merges = process_omm_group(
                dry_run=dry_run,
                gl=gl,
                lead=lead,
                app_sre_usernames=app_sre_usernames,
                pipeline_timeout=pipeline_timeout,
                merge_limit=merge_limit,
                merge_requests=merge_requests,
            )
            merge_batch_size_histogram.labels(project_id=gl.project.id).observe(merges)
            return
        # Lead disappeared but pending labels remain — clean up.
        pending = get_omm_pending_mrs(gl)
        if pending:
            logging.warning(["omm-group", "lead-missing-cleanup", gl.project.name])
            clear_omm_group(dry_run, gl, pending=pending)

    # --- No active group: serial merge path ---
    merges = 0
    merged_labels: set[str] = set()

    for merge_request in merge_requests:
        mr: ProjectMergeRequest = merge_request["mr"]

        if merge_request["error"]:
            logging.info(["skip merge", gl.project.name, mr.iid])
            continue

        if rebase and not is_rebased(mr, gl):
            continue

        if mr.iid in pipeline_cache:
            pipelines = pipeline_cache[mr.iid]
            latest = next(
                (p for p in pipelines if p.status != PipelineStatus.SKIPPED),
                None,
            )
            if latest is not None and latest.status == PipelineStatus.SUCCESS:
                # cached success can be stale; a newer pipeline may have failed
                pipelines = gl.get_merge_request_pipelines(mr)
        else:
            pipelines = gl.get_merge_request_pipelines(mr)
        if not pipelines:
            continue

        if pipeline_timeout is not None:
            timed_out_pipelines = get_timed_out_pipelines(pipelines, pipeline_timeout)
            if timed_out_pipelines:
                clean_pipelines(
                    dry_run=dry_run,
                    gl=gl,
                    fork_project_id=mr.source_project_id,
                    pipelines=timed_out_pipelines,
                )

        pipelines = [p for p in pipelines if p.status != PipelineStatus.SKIPPED]
        if not pipelines:
            continue

        if wait_for_pipeline:
            running_pipelines = [
                p for p in pipelines if p.status == PipelineStatus.RUNNING
            ]
            if running_pipelines:
                if insist and (merges == 0 or not rebase):
                    reload_toggle.reload = True
                    raise InsistOnPipelineError(
                        f"Pipelines for merge request in project '{gl.project.name}' have not completed yet: {mr.iid}"
                    )
                continue

        last_pipeline_result = pipelines[0].status
        if last_pipeline_result != PipelineStatus.SUCCESS:
            continue

        logging.info(["merge", gl.project.name, mr.iid])
        if merges >= merge_limit:
            continue

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
                time_to_merge.labels(
                    project_id=mr.target_project_id, priority=merge_request["priority"]
                ).observe(calculate_time_since_approval(merge_request["approved_at"]))
            except gitlab.exceptions.GitlabMRClosedError as e:
                logging.error(f"unable to merge {mr.iid}: {e}")
                gl.add_label_to_merge_request(mr, MERGE_ERROR)
                continue

        merged_labels.update(get_tenant_labels(mr))
        merges += 1

        if rebase and merges == 1:
            if multi_merge and is_eligible_for_optimistic_merge(mr):
                candidates = form_omm_group(
                    gl=gl,
                    merge_requests=merge_requests,
                    merged_labels=merged_labels,
                )
                if candidates:
                    apply_omm_group_lead(dry_run, gl, mr)
                    apply_omm_pending(dry_run, gl, candidates)
            elif multi_merge:
                # lead has no tenant labels — fall back to serial merge
                logging.info(["omm-group", "lead-ineligible", gl.project.name, mr.iid])
            break

    merge_batch_size_histogram.labels(project_id=gl.project.id).observe(merges)


def get_app_sre_usernames(gl: GitLabApi) -> set[str]:
    return {u.username for u in gl.get_app_sre_group_users()}


def publish_access_token_expiration_metrics(gl: GitLabApi) -> None:
    pats = gl.get_personal_access_tokens()

    for pat in pats:
        if pat.active:
            expiration_date = ensure_utc(
                datetime.strptime(pat.expires_at, EXPIRATION_DATE_FORMAT)  # ruff: ignore[call-datetime-strptime-without-zone]
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
    default_rebase_limit = 8
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
    state = init_state(QONTRACT_INTEGRATION)

    for repo in repos:
        hk = repo["housekeeping"]
        project_url = repo["url"]
        days_interval = hk.get("days_interval") or default_days_interval
        enable_closing = hk.get("enable_closing") or default_enable_closing
        rebase_limit = hk.get("rebase_limit") or default_rebase_limit
        merge_limit = hk.get("merge_limit") or rebase_limit
        consecutive_failure_limit = (
            hk.get("consecutive_failure_limit") or default_consecutive_failure_limit
        )
        pipeline_timeout = hk.get("pipeline_timeout")
        multi_merge = (
            rebase_strategy == RebaseStrategy.ACTIVE_CAP_MULTI_MERGE
            and hk.get("multi_merge", False)
        )
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
            pipeline_cache: dict[int, list[ProjectMergeRequestPipeline]] = {}
            try:
                run_error_healthcheck(
                    dry_run=dry_run,
                    gl=gl,
                    project_merge_requests=project_merge_requests,
                    consecutive_failure_limit=consecutive_failure_limit,
                    pipeline_cache=pipeline_cache,
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
                    pipeline_cache=pipeline_cache,
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
                    pipeline_cache={},
                )
            if rebase:
                rebase_merge_requests(
                    dry_run=dry_run,
                    gl=gl,
                    rebase_limit=rebase_limit,
                    state=state,
                    pipeline_timeout=pipeline_timeout,
                    wait_for_pipeline=wait_for_pipeline,
                    users_allowed_to_label=users_allowed_to_label,
                    strategy=rebase_strategy,
                )
