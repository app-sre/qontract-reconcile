import os
import json
import copy

import reconcile.queries as queries
import utils.throughput as throughput

from utils.gitlab_api import GitLabApi


QONTRACT_INTEGRATION = 'saas-file-owners'


def get_baseline_file_path(io_dir):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, 'baseline.json')


def get_diffs_file_path(io_dir):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, 'diffs.json')


def collect_owners():
    owners = {}
    saas_files = queries.get_saas_files()
    for saas_file in saas_files:
        saas_file_name = saas_file['name']
        owners[saas_file_name] = set()
        owner_roles = saas_file.get('roles')
        if not owner_roles:
            continue
        for owner_role in owner_roles:
            owner_users = owner_role.get('users')
            if not owner_users:
                continue
            for owner_user in owner_users:
                owner_username = owner_user['org_username']
                if owner_user.get('tag_on_merge_requests'):
                    owner_username = f'@{owner_username}'
                owners[saas_file_name].add(owner_username)

    # make owners suitable for json dump
    for k in owners:
        owners[k] = list(owners[k])

    return owners


def collect_state():
    state = []
    saas_files = queries.get_saas_files()
    for saas_file in saas_files:
        saas_file_path = saas_file['path']
        saas_file_name = saas_file['name']
        saas_file_parameters = json.loads(saas_file.get('parameters') or '{}')
        saas_file_definitions = {
            'managed_resource_types': saas_file['managedResourceTypes'],
            'image_patterns': saas_file['imagePatterns']
        }
        resource_templates = saas_file['resourceTemplates']
        for resource_template in resource_templates:
            resource_template_name = resource_template['name']
            resource_template_parameters = \
                json.loads(resource_template.get('parameters') or '{}')
            for target in resource_template['targets']:
                namespace_info = target['namespace']
                namespace = namespace_info['name']
                cluster = namespace_info['cluster']['name']
                environment = namespace_info['environment']['name']
                target_ref = target['ref']
                target_parameters = \
                    json.loads(target.get('parameters') or '{}')
                parameters = {}
                parameters.update(saas_file_parameters)
                parameters.update(resource_template_parameters)
                parameters.update(target_parameters)
                state.append({
                    'saas_file_path': saas_file_path,
                    'saas_file_name': saas_file_name,
                    'resource_template_name': resource_template_name,
                    'cluster': cluster,
                    'namespace': namespace,
                    'environment': environment,
                    'ref': target_ref,
                    'parameters': parameters,
                    'saas_file_definitions': saas_file_definitions
                })
    return state


def collect_baseline():
    owners = collect_owners()
    state = collect_state()
    return {'owners': owners, 'state': state}


def write_baseline_to_file(io_dir, baseline):
    file_path = get_baseline_file_path(io_dir)
    with open(file_path, 'w') as f:
        f.write(json.dumps(baseline))
    throughput.change_files_ownership(io_dir)


def read_baseline_from_file(io_dir):
    file_path = get_baseline_file_path(io_dir)
    with open(file_path, 'r') as f:
        baseline = json.load(f)
    return baseline


def write_diffs_to_file(io_dir, diffs, valid_saas_file_changes_only):
    required_keys = ['saas_file_name', 'environment']
    diffs = [{k: v for k, v in diff.items()
              if k in required_keys}
             for diff in diffs]
    unique_diffs = []
    for diff in diffs:
        if diff not in unique_diffs:
            unique_diffs.append(diff)
    file_path = get_diffs_file_path(io_dir)
    body = {
        'valid_saas_file_changes_only': valid_saas_file_changes_only,
        'items': unique_diffs
    }
    with open(file_path, 'w') as f:
        f.write(json.dumps(body))
    throughput.change_files_ownership(io_dir)


def read_diffs_from_file(io_dir):
    file_path = get_diffs_file_path(io_dir)
    with open(file_path, 'r') as f:
        body = json.load(f)
    diffs = body['items']
    return diffs


def init_gitlab(gitlab_project_id):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id,
                     settings=settings)


def valid_diff(current_state, desired_state):
    """ checks that current_state and desired_state
    are different only in 'ref', 'parameters' or 'disable' between entries """
    current_state_copy = copy.deepcopy(current_state)
    for c in current_state_copy:
        c.pop('ref')
        c.pop('parameters')
        c.pop('disable', None)
    desired_state_copy = copy.deepcopy(desired_state)
    for d in desired_state_copy:
        d.pop('ref')
        d.pop('parameters')
        c.pop('disable', None)
    return current_state_copy == desired_state_copy


def check_if_lgtm(owners, comments):
    if not owners:
        return False
    approved = False
    hold = False
    lgtm_comment = False
    sorted_comments = sorted(comments, key=lambda k: k['created_at'])
    for comment in sorted_comments:
        commenter = comment['username']
        if commenter not in owners:
            continue
        for line in comment['body'].split('\n'):
            if line == '/lgtm':
                lgtm_comment = True
                approved = True
            if line == '/lgtm cancel':
                lgtm_comment = False
                approved = False
            if line == '/hold':
                hold = True
                approved = False
            if line == '/hold cancel' and lgtm_comment:
                hold = False
                approved = True

    return approved, hold


def check_saas_files_changes_only(changed_paths, diffs):
    saas_file_paths = [d['saas_file_path'] for d in diffs]
    non_saas_file_changed_paths = []
    for changed_path in changed_paths:
        found = False
        for saas_file_path in saas_file_paths:
            if changed_path.endswith(saas_file_path):
                found = True
                break
        if not found:
            non_saas_file_changed_paths.append(changed_path)

    return len(non_saas_file_changed_paths) == 0


def run(dry_run, gitlab_project_id=None, gitlab_merge_request_id=None,
        io_dir='throughput/', compare=True):
    if not compare:
        # baseline is the current state and the owners.
        # this should be queried from the production endpoint
        # to prevent privilege escalation and to compare the states
        baseline = collect_baseline()
        write_baseline_to_file(io_dir, baseline)
        return

    approved_label = 'bot/approved'
    hold_label = 'bot/hold'
    gl = init_gitlab(gitlab_project_id)
    baseline = read_baseline_from_file(io_dir)
    owners = baseline['owners']
    current_state = baseline['state']
    desired_state = collect_state()
    diffs = [s for s in desired_state if s not in current_state]
    changed_paths = \
        gl.get_merge_request_changed_paths(gitlab_merge_request_id)
    is_saas_file_changes_only = \
        check_saas_files_changes_only(changed_paths, diffs)
    is_valid_diff = valid_diff(current_state, desired_state)
    valid_saas_file_changes_only = is_saas_file_changes_only and is_valid_diff
    write_diffs_to_file(io_dir, diffs, valid_saas_file_changes_only)

    if desired_state == current_state:
        gl.remove_label_from_merge_request(
            gitlab_merge_request_id, approved_label)
        return
    if not is_valid_diff:
        gl.remove_label_from_merge_request(
            gitlab_merge_request_id, approved_label)
        return

    comments = gl.get_merge_request_comments(gitlab_merge_request_id)
    comment_lines = {}
    for diff in diffs:
        # check for a lgtm by an owner of this app
        saas_file_name = diff['saas_file_name']
        saas_file_owners = owners.get(saas_file_name)
        valid_lgtm, hold = check_if_lgtm(saas_file_owners, comments)
        if hold:
            gl.add_label_to_merge_request(
                gitlab_merge_request_id, hold_label)
        else:
            gl.remove_label_from_merge_request(
                gitlab_merge_request_id, hold_label)
        if not valid_lgtm:
            gl.remove_label_from_merge_request(
                gitlab_merge_request_id, approved_label)
            comment_line_body = \
                f"- changes to saas file '{saas_file_name}' " + \
                f"require approval (`/lgtm`) from one of: {saas_file_owners}."
            comment_lines[saas_file_name] = comment_line_body
            continue

        # this diff is approved - remove it from changed_paths
        saas_file_path = diff['saas_file_path']
        changed_paths = [c for c in changed_paths
                         if not c.endswith(saas_file_path)]

    comment_body = '\n'.join(comment_lines.values())
    if comment_body:
        gl.add_comment_to_merge_request(gitlab_merge_request_id, comment_body)

    # if there are still entries in this list - they are not approved
    if len(changed_paths) != 0:
        gl.remove_label_from_merge_request(
            gitlab_merge_request_id, approved_label)
        return

    # add approved label to merge request!
    gl.add_label_to_merge_request(gitlab_merge_request_id, approved_label)
