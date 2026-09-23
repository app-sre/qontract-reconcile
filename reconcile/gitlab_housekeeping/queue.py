from __future__ import annotations

import logging
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from gitlab.const import PipelineStatus

from reconcile.gitlab_housekeeping.labels import (
    ERROR_LABELS,
    MERGE_LABELS_PRIORITY,
    is_good_to_merge,
)
from reconcile.utils.gitlab_api import MRState, MRStatus
from reconcile.utils.mr.labels import (
    LGTM,
    SAAS_FILE_UPDATE,
    SELF_SERVICEABLE,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from gitlab.v4.objects import (
        ProjectMergeRequest,
    )

    from reconcile.utils.gitlab_api import GitLabApi
    from reconcile.utils.state import State


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


def get_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    state: State,
    users_allowed_to_label: Iterable[str] | None = None,
    skip_unmergeable: bool = True,
) -> list[dict[str, Any]]:
    mrs = gl.get_merge_requests(state=MRState.OPENED)
    return preprocess_merge_requests(
        dry_run=dry_run,
        gl=gl,
        project_merge_requests=mrs,
        state=state,
        users_allowed_to_label=users_allowed_to_label,
        skip_unmergeable=skip_unmergeable,
    )


def preprocess_merge_requests(
    dry_run: bool,
    gl: GitLabApi,
    project_merge_requests: list[ProjectMergeRequest],
    state: State,
    users_allowed_to_label: Iterable[str] | None = None,
    must_pass: Iterable[str] | None = None,
    skip_unmergeable: bool = True,
) -> list[dict[str, Any]]:
    results = []
    for mr in project_merge_requests:
        if mr.merge_status in {
            MRStatus.CANNOT_BE_MERGED,
            MRStatus.CANNOT_BE_MERGED_RECHECK,
        }:
            if skip_unmergeable:
                continue
            # cannot_be_merged_recheck is a transient state GitLab sets for
            # nearly every open MR on every reconcile cycle -- debug only,
            # see run_error_healthcheck() for why this isn't a warning.
            logging.debug([
                "preprocess",
                gl.project.name,
                mr.iid,
                f"merge_status={mr.merge_status}, including for rebase",
            ])
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
