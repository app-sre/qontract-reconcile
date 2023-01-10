import itertools
import logging
import sys

from sretoolbox.utils import threaded

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.utils import (
    expiration,
    gql,
)
from reconcile.utils.defer import defer
from reconcile.utils.oc import OC_Map
from reconcile.utils.sharding import is_in_shard

ROLES_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      org_username
      github_username
    }
    expirationDate
    access {
      cluster {
        name
        auth {
          service
        }
      }
      group
    }
  }
}
"""

GROUPS_QUERY = """
{
  clusters: clusters_v1 {
    name
    managedGroups
    ocm {
      name
    }
  }
}
"""

QONTRACT_INTEGRATION = "openshift-groups"


def get_cluster_state(group_items, oc_map):
    results = []
    cluster = group_items["cluster"]
    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return results
    group_name = group_items["group_name"]
    try:
        group = oc.get_group_if_exists(group_name)
    except Exception as e:
        msg = ("could not get group state for cluster/group combination: {}/{}").format(
            cluster, group_name
        )
        logging.error(msg)
        raise e
    if group is None:
        return results
    for user in group["users"] or []:
        results.append({"cluster": cluster, "group": group_name, "user": user})
    return results


def create_groups_list(clusters, oc_map):
    groups_list = []
    for cluster_info in clusters:
        cluster = cluster_info["name"]
        oc = oc_map.get(cluster)
        if not oc:
            logging.log(level=oc.log_level, msg=oc.message)
        groups = cluster_info["managedGroups"]
        if groups is None:
            continue
        for group_name in groups:
            groups_list.append({"cluster": cluster, "group_name": group_name})
    return groups_list


def fetch_current_state(thread_pool_size, internal, use_jump_host):
    clusters = [c for c in queries.get_clusters() if is_in_shard(c["name"])]
    ocm_clusters = [c["name"] for c in clusters if c.get("ocm") is not None]
    current_state = []
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )

    groups_list = create_groups_list(clusters, oc_map)
    results = threaded.run(
        get_cluster_state, groups_list, thread_pool_size, oc_map=oc_map
    )

    current_state = list(itertools.chain.from_iterable(results))
    return oc_map, current_state, ocm_clusters


def fetch_desired_state(oc_map, enforced_user_keys=None):
    gqlapi = gql.get_api()
    roles = expiration.filter(gqlapi.query(ROLES_QUERY)["roles"])
    desired_state = []

    for r in roles:
        for a in r["access"] or []:
            if None in [a["cluster"], a["group"]]:
                continue
            if oc_map and a["cluster"]["name"] not in oc_map.clusters():
                continue

            user_keys = ob.determine_user_keys_for_access(
                a["cluster"]["name"],
                a["cluster"]["auth"],
                enforced_user_keys=enforced_user_keys,
            )
            for u in r["users"]:
                for username in {u[user_key] for user_key in user_keys}:
                    if username is None:
                        continue

                    desired_state.append(
                        {
                            "cluster": a["cluster"]["name"],
                            "group": a["group"],
                            "user": username,
                        }
                    )

    return desired_state


def calculate_diff(current_state, desired_state):
    diff = []
    users_to_add = subtract_states(
        desired_state, current_state, "add_user_to_group", "create_group"
    )
    diff.extend(users_to_add)
    users_to_del = subtract_states(
        current_state, desired_state, "del_user_from_group", "delete_group"
    )
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
            s_groups = {
                s_user["group"]
                for s_user in subtract_state
                if f_user["cluster"] == s_user["cluster"]
            }
            if f_user["group"] not in s_groups:
                item = {
                    "action": group_action,
                    "cluster": f_user["cluster"],
                    "group": f_user["group"],
                    "user": None,
                }
                if item not in result:
                    result.append(item)
            result.append(
                {
                    "action": user_action,
                    "cluster": f_user["cluster"],
                    "group": f_user["group"],
                    "user": f_user["user"],
                }
            )

    return result


def validate_diffs(diffs):
    gqlapi = gql.get_api()
    clusters_query = gqlapi.query(GROUPS_QUERY)["clusters"]

    desired_combos = [
        {"cluster": diff["cluster"], "group": diff["group"]} for diff in diffs
    ]
    desired_combos_unique = []
    [
        desired_combos_unique.append(item)
        for item in desired_combos
        if item not in desired_combos_unique
    ]

    valid_combos = [
        {"cluster": cluster["name"], "group": group}
        for cluster in clusters_query
        for group in cluster["managedGroups"] or []
    ]

    invalid_combos = [
        item for item in desired_combos_unique if item not in valid_combos
    ]

    if len(invalid_combos) != 0:
        for combo in invalid_combos:
            msg = (
                "invalid cluster/group combination: {}/{}"
                " (hint: should be added to managedGroups)"
            ).format(combo["cluster"], combo["group"])
            logging.error(msg)
        sys.exit(1)


def sort_diffs(diff):
    if diff["action"] in ["create_group", "del_user_from_group"]:
        return 1
    else:
        return 2


def act(diff, oc_map):
    cluster = diff["cluster"]
    group = diff["group"]
    user = diff["user"]
    action = diff["action"]
    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return None

    if action == "create_group":
        oc.create_group(group)
    elif action == "add_user_to_group":
        oc.add_user_to_group(group, user)
    elif action == "del_user_from_group":
        oc.del_user_from_group(group, user)
    elif action == "delete_group":
        logging.debug("skipping group deletion")
    else:
        raise Exception("invalid action: {}".format(action))


@defer
def run(dry_run, thread_pool_size=10, internal=None, use_jump_host=True, defer=None):

    oc_map, current_state, ocm_clusters = fetch_current_state(
        thread_pool_size, internal, use_jump_host
    )
    defer(oc_map.cleanup)
    desired_state = fetch_desired_state(oc_map)

    # we only manage dedicated-admins via OCM
    current_state = [
        s
        for s in current_state
        if not (s["cluster"] in ocm_clusters and s["group"] == "dedicated-admins")
    ]
    desired_state = [
        s
        for s in desired_state
        if not (s["cluster"] in ocm_clusters and s["group"] == "dedicated-admins")
    ]

    diffs = calculate_diff(current_state, desired_state)
    validate_diffs(diffs)
    diffs.sort(key=sort_diffs)

    for diff in diffs:
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, oc_map)
