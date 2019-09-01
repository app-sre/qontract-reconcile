import sys
import logging

from multiprocessing.dummy import Pool as ThreadPool
from functools import partial

import utils.gql as gql

from utils.oc import OC_Map

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

GROUPS_QUERY = """
{
  clusters: clusters_v1 {
    name
    managedGroups
  }
}
"""


def get_cluster_state(group_items, oc_map):
    results = []
    cluster = group_items["cluster"]
    oc = oc_map.get(cluster)
    group_name = group_items["group_name"]
    group = oc.get_group_if_exists(group_name)
    if group is None:
        return results
    for user in group['users'] or []:
        results.append({
            "cluster": cluster,
            "group": group_name,
            "user": user
        })
    return results


def create_groups_list(clusters):
    groups_list = []
    for cluster_info in clusters:
        groups = cluster_info['managedGroups']
        cluster = cluster_info['name']
        if groups is None:
            continue
        for group_name in groups:
            groups_list.append({
                    "cluster": cluster,
                    "group_name": group_name
                })
    return groups_list


def fetch_current_state(thread_pool_size):
    gqlapi = gql.get_api()
    clusters = gqlapi.query(CLUSTERS_QUERY)['clusters']
    current_state = []
    oc_map = OC_Map(clusters=clusters)

    pool = ThreadPool(thread_pool_size)
    groups_list = create_groups_list(clusters)
    get_cluster_state_partial = \
        partial(get_cluster_state, oc_map=oc_map)
    results = pool.map(get_cluster_state_partial, groups_list)
    current_state = [item for sublist in results for item in sublist]
    return oc_map, current_state


def fetch_desired_state():
    gqlapi = gql.get_api()
    roles = gqlapi.query(ROLES_QUERY)['roles']
    desired_state = []

    for r in roles:
        for p in r['permissions']:
            if 'service' not in p:
                continue
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
        subtract_states(desired_state, current_state,
                        "add_user_to_group", "create_group")
    diff.extend(users_to_add)
    users_to_del = \
        subtract_states(current_state, desired_state,
                        "del_user_from_group", "delete_group")
    diff.extend(users_to_del)

    return diff


def subtract_states(from_state, subtract_state, user_action, group_action):
    result = []

    for f_user in from_state:
        found = False
        for s_user in subtract_state:
            if f_user != s_user:
                continue
            found = True
            break
        if not found:
            s_groups = set([s_user['group']
                            for s_user in subtract_state
                            if f_user['cluster'] == s_user['cluster']])
            if f_user['group'] not in s_groups:
                item = {
                    "action": group_action,
                    "cluster": f_user['cluster'],
                    "group": f_user['group'],
                    "user": None
                }
                if item not in result:
                    result.append(item)
            result.append({
                "action": user_action,
                "cluster": f_user['cluster'],
                "group": f_user['group'],
                "user": f_user['user']
            })

    return result


def validate_diffs(diffs):
    gqlapi = gql.get_api()
    clusters_query = gqlapi.query(GROUPS_QUERY)['clusters']

    desired_combos = [{"cluster": diff['cluster'], "group": diff['group']}
                      for diff in diffs]
    desired_combos_unique = []
    [desired_combos_unique.append(item)
     for item in desired_combos
     if item not in desired_combos_unique]

    valid_combos = [{"cluster": cluster['name'], "group": group}
                    for cluster in clusters_query
                    for group in cluster['managedGroups'] or []]

    invalid_combos = [item for item in desired_combos_unique
                      if item not in valid_combos]

    if len(invalid_combos) != 0:
        for combo in invalid_combos:
            msg = (
                'invalid cluster/group combination: {}/{}'
                ' (hint: should be added to managedGroups)'
            ).format(combo['cluster'], combo['group'])
            logging.error(msg)
        sys.exit(1)


def sort_diffs(diff):
    if diff['action'] in ['create_group', 'del_user_from_group']:
        return 1
    else:
        return 2


def act(diff, oc_map):
    cluster = diff['cluster']
    group = diff['group']
    user = diff['user']
    action = diff['action']
    oc = oc_map.get(cluster)

    if action == "create_group":
        oc.create_group(group)
    elif action == "add_user_to_group":
        oc.add_user_to_group(group, user)
    elif action == "del_user_from_group":
        oc.del_user_from_group(group, user)
    elif action == "delete_group":
        oc.delete_group(group)
    else:
        raise Exception("invalid action: {}".format(action))


def run(dry_run=False, thread_pool_size=10):
    oc_map, current_state = fetch_current_state(thread_pool_size)
    desired_state = fetch_desired_state()

    diffs = calculate_diff(current_state, desired_state)
    validate_diffs(diffs)
    diffs.sort(key=sort_diffs)

    for diff in diffs:
        logging.info(diff.values())

        if not dry_run:
            act(diff, oc_map)
