import os
import json

import reconcile.queries as queries


QONTRACT_INTEGRATION = 'owner-approvals'


def get_owners_file_path(io_dir):
    dir_path = os.path.join(io_dir, QONTRACT_INTEGRATION)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    return os.path.join(dir_path, 'owners.json')


def collect_owners_to_file(io_dir):
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

    # write owners to throughput file
    file_path = get_owners_file_path(io_dir)
    with open(file_path, 'w') as f:
        f.write(json.dumps(owners))


def read_owners_from_file(io_dir):
    file_path = get_owners_file_path(io_dir)
    with open(file_path, 'r') as f:
        owners = json.load(f)
    return owners


def run(dry_run=False, io_dir='throughput/', compare=True):
    if not compare:
        collect_owners_to_file(io_dir)
        return

    owners = read_owners_from_file(io_dir)
