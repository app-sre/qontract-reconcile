import os
import json
import copy

import reconcile.queries as queries
from utils.gitlab_api import GitLabApi


QONTRACT_INTEGRATION = 'owner-approvals'


def get_baseline_file_path(io_dir):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, 'baseline.json')


def collect_owners():
    owners = {}
    apps = queries.get_apps()
    for app in apps:
        app_name = app['name']
        owners[app_name] = set()
        owner_roles = app.get('owner_roles')
        if not owner_roles:
            continue
        for owner_role in owner_roles:
            owner_users = owner_role.get('users')
            if not owner_users:
                continue
            for owner_user in owner_users:
                owner_username = owner_user['org_username']
                owners[app_name].add(owner_username)

    # make owners suitable for json dump
    for k in owners:
        owners[k] = list(owners[k])

    return owners


def collect_state():
    state = []
    saas_files = queries.get_saas_files()
    for sf in saas_files:
        path = sf['path']
        app = sf['app']['name']
        resource_templates = sf['resourceTemplates']
        for rt in resource_templates:
            rt_name = rt['name']
            for target in rt['targets']:
                namespace = target['namespace']['name']
                cluster = target['namespace']['cluster']['name']
                target_hash = target['hash']
                state.append({
                    'path': path,
                    'app': app,
                    'name': rt_name,
                    'cluster': cluster,
                    'namespace': namespace,
                    'hash': target_hash
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


def read_baseline_from_file(io_dir):
    file_path = get_baseline_file_path(io_dir)
    with open(file_path, 'r') as f:
        baseline = json.load(f)
    return baseline


def init_gitlab(gitlab_project_id):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id,
                     settings=settings)


def valid_diff(current_state, desired_state):
    """ checks that current_state and desired_state
    are different only in 'hash' between entries """
    current_state_copy = copy.deepcopy(current_state)
    for c in current_state_copy:
        c.pop('hash')
    desired_state_copy = copy.deepcopy(desired_state)
    for d in desired_state_copy:
        d.pop('hash')
    return current_state_copy == desired_state_copy


def run(gitlab_project_id, gitlab_merge_request_id, dry_run=False,
        io_dir='throughput/', compare=True):
    if not compare:
        # baseline is the current state and the owners.
        # this should be queried from the production endpoint
        # to prevent privlige escalation and to compare the states
        baseline = collect_baseline()
        write_baseline_to_file(io_dir, baseline)
        return

    gl = init_gitlab(gitlab_project_id)
    baseline = read_baseline_from_file(io_dir)
    owners = baseline['owners']
    current_state = baseline['state']
    desired_state = collect_state()

    if desired_state == current_state:
        gl.remove_label_from_merge_request(
            gitlab_merge_request_id, 'approved')
        return
    if not valid_diff(current_state, desired_state):
        gl.remove_label_from_merge_request(
            gitlab_merge_request_id, 'approved')
        return


    comments = gl.get_merge_request_comments(gitlab_merge_request_id)
    lgtm_users = [c['username'] for c in comments
                  for l in c['body'].split('\n')
                  if l == '/lgtm']
    if len(lgtm_users) == 0:
        gl.remove_label_from_merge_request(
            gitlab_merge_request_id, 'approved')
        return

    changed_paths = \
        gl.get_merge_request_changed_paths(gitlab_merge_request_id)
    diffs = [s for s in desired_state if s not in current_state]
    for diff in diffs:
        # check for a lgtm by an owner of this app
        app = diff['app']
        if not any(lgtm_user in owners[app] for lgtm_user in lgtm_users):
            gl.remove_label_from_merge_request(
                gitlab_merge_request_id, 'approved')
            return
        # this diff is approved - remove it from changed_paths
        path = diff['path']
        changed_paths = [c for c in changed_paths if not c.endswith(path)]

    # if there are still entries in this list - they are not approved
    if len(changed_paths) != 0:
        gl.remove_label_from_merge_request(
            gitlab_merge_request_id, 'approved')
        return

    # add 'approved' label to merge request!
    gl.add_label_to_merge_request(gitlab_merge_request_id, 'approved')
