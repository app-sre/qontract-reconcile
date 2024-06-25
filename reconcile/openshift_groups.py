import itertools
import logging
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any

from sretoolbox.utils import threaded

import reconcile.openshift_base as ob
from reconcile.gql_definitions.openshift_groups.managed_groups import (
    query as query_managed_groups,
)
from reconcile.gql_definitions.openshift_groups.managed_roles import (
    query as query_managed_roles,
)
from reconcile.openshift_base import ClusterMap
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils import (
    expiration,
    gql,
)
from reconcile.utils.defer import defer
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
    init_oc_map_from_clusters,
)
from reconcile.utils.ocm.base import OCMClusterGroupId
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.sharding import is_in_shard

QONTRACT_INTEGRATION = "openshift-groups"


def get_cluster_state(
    group_items: Mapping[str, str], oc_map: ClusterMap
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    cluster = group_items["cluster"]
    oc = oc_map.get(cluster)
    if isinstance(oc, OCLogMsg):
        logging.log(level=oc.log_level, msg=oc.message)
        return results
    group_name = group_items["group_name"]
    try:
        group = oc.get_group_if_exists(group_name)
    except Exception as e:
        msg = f"could not get group state for cluster/group combination: {cluster}/{group_name}"
        logging.error(msg)
        raise e
    if group is None:
        return results
    for user in group["users"] or []:
        results.append({"cluster": cluster, "group": group_name, "user": user})
    return results


def create_groups_list(
    clusters: Iterable[Mapping[str, Any]], oc_map: ClusterMap
) -> list[dict[str, str]]:
    """
    Also used by ocm-groups integration and thus requires to work with dict for now
    """
    groups_list: list[dict[str, str]] = []
    for cluster_info in clusters:
        cluster = cluster_info["name"]
        oc = oc_map.get(cluster)
        if isinstance(oc, OCLogMsg):
            logging.log(level=oc.log_level, msg=oc.message)
        groups = cluster_info["managedGroups"] or []
        for group_name in groups:
            groups_list.append({"cluster": cluster, "group_name": group_name})
    return groups_list


def fetch_current_state(
    thread_pool_size: int, internal: bool | None, use_jump_host: bool
) -> tuple[OCMap, list[dict[str, str]], list[str], list[dict[str, str]]]:
    clusters = [c for c in get_clusters() if is_in_shard(c.name)]
    ocm_clusters = [c.name for c in clusters if c.ocm is not None]
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    current_state = []
    oc_map = init_oc_map_from_clusters(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
    )

    groups_list = create_groups_list([c.dict(by_alias=True) for c in clusters], oc_map)
    results = threaded.run(
        get_cluster_state, groups_list, thread_pool_size, oc_map=oc_map
    )

    current_state = list(itertools.chain.from_iterable(results))
    return oc_map, current_state, ocm_clusters, groups_list


def fetch_desired_state(
    clusters: list[str], enforced_user_keys: list[str] | None = None
) -> list[dict[str, str]]:
    gqlapi = gql.get_api()
    roles = expiration.filter(query_managed_roles(query_func=gqlapi.query).roles or [])
    desired_state: list[dict[str, str]] = []

    for r in roles:
        for a in r.access or []:
            if not a.cluster or not a.group:
                continue
            if clusters and a.cluster.name not in clusters:
                continue

            user_keys = ob.determine_user_keys_for_access(
                a.cluster.name,
                a.cluster.auth,
                enforced_user_keys=enforced_user_keys,
            )
            for u in r.users:
                for username in {getattr(u, user_key) for user_key in user_keys}:
                    if username is None:
                        continue

                    desired_state.append({
                        "cluster": a.cluster.name,
                        "group": a.group,
                        "user": username,
                    })

    return desired_state


def calculate_diff(
    current_state: Iterable[Mapping[str, str]],
    desired_state: Iterable[Mapping[str, str]],
) -> list[dict[str, str | None]]:
    diff: list[dict[str, str | None]] = []
    users_to_add = subtract_states(
        desired_state, current_state, "add_user_to_group", "create_group"
    )
    diff.extend(users_to_add)
    users_to_del = subtract_states(
        current_state, desired_state, "del_user_from_group", "delete_group"
    )
    diff.extend(users_to_del)

    return diff


def subtract_states(
    from_state: Iterable[Mapping[str, str]],
    subtract_state: Iterable[Mapping[str, str]],
    user_action: str,
    group_action: str,
) -> list[dict[str, str | None]]:
    result: list[dict[str, str | None]] = []

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
            result.append({
                "action": user_action,
                "cluster": f_user["cluster"],
                "group": f_user["group"],
                "user": f_user["user"],
            })

    return result


def validate_diffs(diffs: Iterable[Mapping[str, str | None]]) -> None:
    gqlapi = gql.get_api()
    clusters_query = query_managed_groups(query_func=gqlapi.query).clusters or []

    desired_combos = [
        {"cluster": diff["cluster"], "group": diff["group"]} for diff in diffs
    ]
    desired_combos_unique: list[dict[str, str | None]] = []
    for combo in desired_combos:
        if combo in desired_combos_unique:
            continue
        desired_combos_unique.append(combo)

    valid_combos = [
        {"cluster": cluster.name, "group": group}
        for cluster in clusters_query
        for group in cluster.managed_groups or []
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
        raise RuntimeError(msg)


def sort_diffs(diff: Mapping[str, str | None]) -> int:
    if diff["action"] in {"create_group", "del_user_from_group"}:
        return 1
    return 2


def act(diff: Mapping[str, str | None], oc_map: ClusterMap) -> None:
    cluster = diff.get("cluster") or ""
    group = diff["group"]
    user = diff["user"]
    action = diff["action"]
    oc = oc_map.get(cluster)
    if isinstance(oc, OCLogMsg):
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
        raise Exception(f"invalid action: {action}")


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    oc_map, current_state, ocm_clusters, groups_list = fetch_current_state(
        thread_pool_size, internal, use_jump_host
    )
    if defer:
        defer(oc_map.cleanup)
    desired_state = fetch_desired_state(oc_map.clusters())

    current_state = [
        s
        for s in current_state
        if not (
            s["cluster"] in ocm_clusters and s["group"] in OCMClusterGroupId.values()
        )
    ]
    desired_state = [
        s
        for s in desired_state
        if not (
            s["cluster"] in ocm_clusters and s["group"] in OCMClusterGroupId.values()
        )
    ]

    ob.publish_cluster_desired_metrics_from_state(
        groups_list, QONTRACT_INTEGRATION, "Group"
    )
    diffs = calculate_diff(current_state, desired_state)
    validate_diffs(diffs)
    diffs.sort(key=sort_diffs)

    for diff in diffs:
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, oc_map)
