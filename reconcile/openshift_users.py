import itertools
import logging

from sretoolbox.utils import threaded

from reconcile import (
    openshift_groups,
    openshift_rolebindings,
    queries,
)
from reconcile.utils.defer import defer
from reconcile.utils.oc import OC_Map

QONTRACT_INTEGRATION = "openshift-users"


def get_cluster_users(cluster, oc_map, clusters):
    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return []
    users: list[str] = []

    # get cluster info for current cluster name from clusters list
    cluster_info = next((cl for cl in clusters if cl["name"] == cluster))

    # backwarts compatibiltiy for clusters w/o auth
    identity_prefixes = ["github"]

    for auth in cluster_info["auth"]:
        if auth["service"] == "oidc":
            identity_prefixes.append(auth["name"])

    for u in oc.get_users():
        if u["metadata"].get("labels", {}).get("admin", ""):
            # ignore admins
            continue
        if any(
            identity.startswith(identity_prefix)
            for identity in u.get("identities", [])
            for identity_prefix in identity_prefixes
        ):
            # the user has at least one identitiy which is managed by app-interface
            users.append(u["metadata"]["name"])

    return [{"cluster": cluster, "user": user} for user in users]


def fetch_current_state(thread_pool_size, internal, use_jump_host):
    clusters = queries.get_clusters(minimal=True)
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )
    results = threaded.run(
        get_cluster_users,
        oc_map.clusters(include_errors=True),
        thread_pool_size,
        oc_map=oc_map,
        clusters=clusters,
    )
    current_state = list(itertools.chain.from_iterable(results))
    return oc_map, current_state


def fetch_desired_state(oc_map):
    desired_state = []
    flat_rolebindings_desired_state = openshift_rolebindings.fetch_desired_state(
        ri=None, oc_map=oc_map
    )
    desired_state.extend(flat_rolebindings_desired_state)

    groups_desired_state = openshift_groups.fetch_desired_state(oc_map)
    flat_groups_desired_state = [
        {"cluster": s["cluster"], "user": s["user"]} for s in groups_desired_state
    ]
    desired_state.extend(flat_groups_desired_state)

    return desired_state


def calculate_diff(current_state, desired_state):
    diff = []
    users_to_del = subtract_states(current_state, desired_state, "del_user")
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
            result.append(
                {"action": action, "cluster": f_user["cluster"], "user": f_user["user"]}
            )

    return result


def act(diff, oc_map):
    cluster = diff["cluster"]
    user = diff["user"]
    action = diff["action"]

    if action == "del_user":
        oc_map.get(cluster).delete_user(user)
    else:
        raise Exception("invalid action: {}".format(action))


@defer
def run(dry_run, thread_pool_size=10, internal=None, use_jump_host=True, defer=None):
    oc_map, current_state = fetch_current_state(
        thread_pool_size, internal, use_jump_host
    )
    defer(oc_map.cleanup)
    desired_state = fetch_desired_state(oc_map)

    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, oc_map)
