import os
import json

import reconcile.queries as queries


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
        app = sf['app']['name']
        resource_templates = sf['resourceTemplates']
        for rt in resource_templates:
            rt_name = rt['name']
            for target in rt['targets']:
                namespace = target['namespace']['name']
                cluster = target['namespace']['cluster']['name']
                target_hash = target['hash']
                state.append({
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


def run(dry_run=False, io_dir='throughput/', compare=True):
    if not compare:
        # baseline is the current state and the owners.
        # this should be queried from the production endpoint
        # to prevent privlige escalation and to compare the states
        baseline = collect_baseline()
        write_baseline_to_file(io_dir, baseline)

    baseline = read_baseline_from_file(io_dir)
    print(json.dumps(baseline))
