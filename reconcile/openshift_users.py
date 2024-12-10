import itertools
import logging
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any

from sretoolbox.utils import threaded

from reconcile import (
    openshift_groups,
    openshift_rolebindings,
)
from reconcile.gql_definitions.common.clusters_minimal import (
    ClusterAuthOIDCV1,
    ClusterAuthRHIDPV1,
    ClusterV1,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.utils.defer import defer
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
    init_oc_map_from_clusters,
)
from reconcile.utils.secret_reader import create_secret_reader

QONTRACT_INTEGRATION = "openshift-users"


def get_cluster_users(
    cluster: str, oc_map: OCMap, clusters: Iterable[ClusterV1]
) -> list[dict[str, Any]]:
    oc = oc_map.get(cluster)
    if isinstance(oc, OCLogMsg):
        logging.log(level=oc.log_level, msg=oc.message)
        return []
    users: list[str] = []

    # get cluster info for current cluster name from clusters list
    cluster_info = next(cl for cl in clusters if cl.name == cluster)

    # backwarts compatibiltiy for clusters w/o auth
    identity_prefixes = ["github"]
    identity_prefixes.extend(
        auth.name
        for auth in cluster_info.auth
        if isinstance(auth, ClusterAuthOIDCV1 | ClusterAuthRHIDPV1)
    )

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


def fetch_current_state(
    thread_pool_size: int,
    internal: bool | None,
    use_jump_host: bool,
) -> tuple[OCMap, list[Any]]:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    clusters = get_clusters_minimal()

    oc_map = init_oc_map_from_clusters(
        clusters=clusters,
        secret_reader=secret_reader,
        integration=QONTRACT_INTEGRATION,
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


def fetch_desired_state(
    oc_map: OCMap | None, enforced_user_keys: Any = None
) -> list[Any]:
    desired_state = []

    flat_rolebindings_desired_state = openshift_rolebindings.fetch_desired_state(
        ri=None, oc_map=oc_map, enforced_user_keys=enforced_user_keys
    )
    desired_state.extend(flat_rolebindings_desired_state)

    groups_desired_state = openshift_groups.fetch_desired_state(
        clusters=oc_map.clusters() if oc_map else [],
        enforced_user_keys=enforced_user_keys,
    )
    flat_groups_desired_state = [
        {"cluster": s["cluster"], "user": s["user"]} for s in groups_desired_state
    ]
    desired_state.extend(flat_groups_desired_state)

    return desired_state


def calculate_diff(
    current_state: Iterable[Any], desired_state: Iterable[Any]
) -> list[dict[str, Any]]:
    diff = []
    users_to_del = subtract_states(current_state, desired_state, "del_user")
    diff.extend(users_to_del)

    return diff


def subtract_states(
    from_state: Iterable[Any], subtract_state: Iterable[Any], action: Any
) -> list[dict[str, Any]]:
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
                "cluster": f_user["cluster"],
                "user": f_user["user"],
            })

    return result


def act(diff: Mapping[str, Any], oc_map: OCMap) -> None:
    cluster = diff["cluster"]
    user = diff["user"]
    action = diff["action"]

    if action == "del_user":
        oc = oc_map.get(cluster)
        if not oc or isinstance(oc, OCLogMsg):
            raise Exception("No proper Openshift Client for del_user operation")
        oc.delete_user(user)
    else:
        raise Exception(f"invalid action: {action}")


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    oc_map, current_state = fetch_current_state(
        thread_pool_size, internal, use_jump_host
    )
    if defer:
        defer(oc_map.cleanup)
    desired_state = fetch_desired_state(oc_map)

    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, oc_map)
