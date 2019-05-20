import logging

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources

CLUSTERS_QUERY = """
{
  clusters: clusters_v1 {
    name
    serverUrl
    managedGroups
    jumpHost {
      hostname
      knownHosts
      user
      port
      identity {
        path
        field
        format
      }
    }
    automationToken {
      path
      field
      format
    }
  }
}
"""

ROLES_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      github_username
    }
    permissions {
      ...on PermissionOpenshiftGroup_v1 {
        service
        cluster
        group
      }
    }
  }
}
"""


def fetch_current_state():
    gqlapi = gql.get_api()
    clusters = gqlapi.query(CLUSTERS_QUERY)['clusters']
    current_state = []
    oc_map = {}

    for cluster_info in clusters:
        groups = cluster_info['managedGroups']
        if groups is None:
            continue

        cluster = cluster_info['name']
        oc = openshift_resources.obtain_oc_client(oc_map, cluster_info)
        oc_map[cluster] = oc

        for group_name in groups:
            group = oc.get(None, 'Group', group_name)
            for user in group['users']:
                current_state.append({
                    "cluster": cluster,
                    "group": group_name,
                    "user": user
                })

    return oc_map, current_state


def fetch_desired_state():
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    desired_state = []

    for r in roles:
        for p in r['permissions']:
            if p['service'] != 'openshift-group':
                continue

            for u in r['users']:
                if u['github_username'] is None:
                    continue

                desired_state.append({
                    "cluster": p['cluster'],
                    "group": p['group'],
                    "user": u['github_username']
                })

    return desired_state


def calculate_diff(current_state, desired_state):
    diff = []
    users_to_add = \
        subtract_states(desired_state, current_state, "add_user_to_group")
    diff.extend(users_to_add)
    users_to_del = \
        subtract_states(current_state, desired_state, "del_user_from_group")
    diff.extend(users_to_del)

    return diff


def subtract_states(from_state, subtract_state, action):
    result = []

    for f_user in from_state:
        found = False
        for s_user in subtract_state:
            if f_user != s_user:
                continue
            found = True
            break
        if not found:
            result.append({
                "action": action,
                "cluster": f_user['cluster'],
                "group": f_user['group'],
                "user": f_user['user']
            })

    return result


def act(diff, oc_map):
    cluster = diff['cluster']
    group = diff['group']
    user = diff['user']
    action = diff['action']

    if action == "add_user_to_group":
        oc_map[cluster].add_user_to_group(group, user)
    elif action == "del_user_from_group":
        oc_map[cluster].del_user_from_group(group, user)
    else:
        raise Exception("invalid action: {}".format(action))


def run(dry_run=False):
    oc_map, current_state = fetch_current_state()
    desired_state = fetch_desired_state()

    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(diff.values())

        if not dry_run:
            act(diff, oc_map)
