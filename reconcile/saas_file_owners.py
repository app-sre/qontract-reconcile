import os
import json
import copy
import logging

from reconcile import queries
from reconcile.openshift_saas_deploy_change_tester import (
    collect_state,
    collect_compare_diffs,
)
from reconcile.utils import throughput

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.labels import APPROVED, HOLD, SAAS_FILE_UPDATE


QONTRACT_INTEGRATION = "saas-file-owners"


def get_baseline_file_path(io_dir):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, "baseline.json")


def get_diffs_file_path(io_dir):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, "diffs.json")


def collect_owners():
    owners = {}
    saas_files = queries.get_saas_files()
    for saas_file in saas_files:
        saas_file_name = saas_file["name"]
        owners[saas_file_name] = set()
        # self-service configs
        for self_service_role in saas_file.get("selfServiceRoles") or []:
            owner_users = self_service_role.get("users") or []
            for owner_user in owner_users:
                owner_username = owner_user["org_username"]
                if owner_user.get("tag_on_merge_requests"):
                    owner_username = f"@{owner_username}"
                owners[saas_file_name].add(owner_username)
            owner_bots = self_service_role.get("bots") or []
            for bot in owner_bots:
                bot_org_username = bot.get("org_username")
                if bot_org_username:
                    owners[saas_file_name].add(bot_org_username)

    # make owners suitable for json dump
    ans = {}
    for k, v in owners.items():
        ans[k] = list(v)

    return ans


def collect_baseline():
    owners = collect_owners()
    saas_files = queries.get_saas_files()
    state = collect_state(saas_files)
    return {"owners": owners, "state": state}


def write_baseline_to_file(io_dir, baseline):
    file_path = get_baseline_file_path(io_dir)
    with open(file_path, "w") as f:
        f.write(json.dumps(baseline))
    throughput.change_files_ownership(io_dir)


def read_baseline_from_file(io_dir):
    file_path = get_baseline_file_path(io_dir)
    with open(file_path, "r") as f:
        baseline = json.load(f)
    return baseline


def write_diffs_to_file(io_dir, diffs, valid_saas_file_changes_only):
    required_keys = ["saas_file_name", "environment"]
    diffs = [{k: v for k, v in diff.items() if k in required_keys} for diff in diffs]
    unique_diffs = []
    for diff in diffs:
        if diff not in unique_diffs:
            unique_diffs.append(diff)
    file_path = get_diffs_file_path(io_dir)
    body = {
        "valid_saas_file_changes_only": valid_saas_file_changes_only,
        "items": unique_diffs,
    }
    with open(file_path, "w") as f:
        f.write(json.dumps(body))
    throughput.change_files_ownership(io_dir)


def read_diffs_from_file(io_dir):
    file_path = get_diffs_file_path(io_dir)
    with open(file_path, "r") as f:
        body = json.load(f)
    diffs = body["items"]
    return diffs


def init_gitlab(gitlab_project_id):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id, settings=settings)


def valid_diff(current_state, desired_state):
    """checks that current_state and desired_state
    are different only in 'ref', 'parameters' or 'disable' between entries"""
    current_state_copy = copy.deepcopy(current_state)
    for c in current_state_copy:
        c.pop("ref")
        c.pop("parameters")
        c.pop("secret_parameters")
        c["saas_file_definitions"].pop("use_channel_in_image_tag")
        c.pop("upstream")
        c.pop("disable")
        c.pop("saas_file_deploy_resources")
    desired_state_copy = copy.deepcopy(desired_state)
    for d in desired_state_copy:
        d.pop("ref")
        d.pop("parameters")
        d.pop("secret_parameters")
        d["saas_file_definitions"].pop("use_channel_in_image_tag")
        d.pop("upstream")
        d.pop("disable")
        d.pop("saas_file_deploy_resources")
    return current_state_copy == desired_state_copy


def check_if_lgtm(owners, comments):
    if not owners:
        return False, False
    approved = False
    hold = False
    lgtm_comment = False
    sorted_comments = sorted(comments, key=lambda k: k["created_at"])
    owners = [u.replace("@", "") for u in owners]
    for comment in sorted_comments:
        commenter = comment["username"]
        if commenter not in owners:
            continue
        for line in comment.get("body", "").split("\n"):
            if line == "/lgtm":
                lgtm_comment = True
                approved = True
            if line == "/lgtm cancel":
                lgtm_comment = False
                approved = False
            if line == "/hold":
                hold = True
                approved = False
            if line == "/hold cancel":
                hold = False
                if lgtm_comment:
                    approved = True

    return approved, hold


def check_saas_files_changes_only(changed_paths, diffs):
    saas_file_paths = [d["saas_file_path"] for d in diffs]
    saas_file_target_paths = [d["target_path"] for d in diffs]
    non_saas_file_changed_paths = []
    for changed_path in changed_paths:
        found = False
        for saas_file_path in saas_file_paths:
            if changed_path.endswith(saas_file_path):
                found = True
                break
        for saas_file_target_path in saas_file_target_paths:
            if saas_file_target_path and changed_path.endswith(saas_file_target_path):
                found = True
                break
        if not found:
            non_saas_file_changed_paths.append(changed_path)

    return len(non_saas_file_changed_paths) == 0 and len(changed_paths) != 0


def run(
    dry_run,
    gitlab_project_id=None,
    gitlab_merge_request_id=None,
    io_dir="throughput/",
    compare=True,
):
    if not compare:
        # baseline is the current state and the owners.
        # this should be queried from the production endpoint
        # to prevent privilege escalation and to compare the states
        baseline = collect_baseline()
        write_baseline_to_file(io_dir, baseline)
        return

    gl = init_gitlab(gitlab_project_id)
    baseline = read_baseline_from_file(io_dir)
    owners = baseline["owners"]
    current_state = baseline["state"]
    desired_state = collect_state(queries.get_saas_files())
    diffs = [s for s in desired_state if s not in current_state]
    changed_paths = gl.get_merge_request_changed_paths(gitlab_merge_request_id)

    compare_diffs = collect_compare_diffs(current_state, desired_state, changed_paths)
    if compare_diffs:
        compare_diffs_comment_body = "Diffs:\n" + "\n".join(
            [f"- {d}" for d in compare_diffs]
        )
        gl.add_comment_to_merge_request(
            gitlab_merge_request_id, compare_diffs_comment_body
        )

    is_saas_file_changes_only = check_saas_files_changes_only(changed_paths, diffs)
    is_valid_diff = valid_diff(current_state, desired_state)
    valid_saas_file_changes_only = is_saas_file_changes_only and is_valid_diff
    write_diffs_to_file(io_dir, diffs, valid_saas_file_changes_only)

    # print 'yes' or 'no' to allow pr-check to understand if changes
    # are only valid saas file changes (and exclude other integrations)
    output = "yes" if valid_saas_file_changes_only else "no"
    print(output)

    labels = gl.get_merge_request_labels(gitlab_merge_request_id)
    if valid_saas_file_changes_only and SAAS_FILE_UPDATE not in labels:
        gl.add_label_to_merge_request(gitlab_merge_request_id, SAAS_FILE_UPDATE)
    if not valid_saas_file_changes_only and SAAS_FILE_UPDATE in labels:
        gl.remove_label_from_merge_request(gitlab_merge_request_id, SAAS_FILE_UPDATE)

    if desired_state == current_state:
        gl.remove_label_from_merge_request(gitlab_merge_request_id, APPROVED)
        return
    if not is_valid_diff:
        gl.remove_label_from_merge_request(gitlab_merge_request_id, APPROVED)
        return

    comments = gl.get_merge_request_comments(
        gitlab_merge_request_id, include_description=True
    )
    comment_lines = {}
    hold = False
    changed_paths_copy = changed_paths.copy()
    for diff in diffs:
        # check if this diff was actually changed in the current MR
        saas_file_path = diff["saas_file_path"]
        changed_path_matches = [
            c for c in changed_paths_copy if c.endswith(saas_file_path)
        ]
        saas_file_target_path = diff["target_path"]
        if saas_file_target_path:
            changed_path_matches.extend(
                c for c in changed_paths_copy if c.endswith(saas_file_target_path)
            )
        if not changed_path_matches:
            # this diff was found in the graphql endpoint comparison
            # but is not a part of the changed paths.
            # the only knows case for this currently is if a previous MR
            # that chages another saas file was merged but is not yet
            # reflected in the baseline graphql endpoint.
            # https://issues.redhat.com/browse/APPSRE-3029
            logging.warning(f"Diff not found in changed paths, skipping: {str(diff)}")
            continue
        # check for a lgtm by an owner of this app
        saas_file_name = diff["saas_file_name"]
        saas_file_owners = owners.get(saas_file_name)
        valid_lgtm, current_hold = check_if_lgtm(saas_file_owners, comments)
        hold = hold or current_hold
        if hold:
            gl.add_label_to_merge_request(gitlab_merge_request_id, HOLD)
        else:
            gl.remove_label_from_merge_request(gitlab_merge_request_id, HOLD)
        if not valid_lgtm:
            gl.remove_label_from_merge_request(gitlab_merge_request_id, APPROVED)
            comment_line_body = (
                f"- changes to saas file '{saas_file_name}' "
                + f"require approval (`/lgtm`) from one of: {saas_file_owners}."
            )
            comment_lines[saas_file_name] = comment_line_body
            continue

        # this diff is approved - remove it from changed_paths
        changed_paths = [c for c in changed_paths if c not in changed_path_matches]

    comment_body = "\n".join(comment_lines.values())
    if comment_body:
        # if there are still entries in this list - they are not approved
        if not valid_saas_file_changes_only:
            comment_body = (
                comment_body + "\n\nNote: this merge request can not be self-serviced."
            )
        gl.add_comment_to_merge_request(gitlab_merge_request_id, comment_body)

    # if there are still entries in this list - they are not approved
    if len(changed_paths) != 0:
        gl.remove_label_from_merge_request(gitlab_merge_request_id, APPROVED)
        return

    if not valid_saas_file_changes_only:
        return

    # add approved label to merge request!
    gl.add_label_to_merge_request(gitlab_merge_request_id, APPROVED)
