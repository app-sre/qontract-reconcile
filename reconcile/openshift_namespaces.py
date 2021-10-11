import logging
import sys

from typing import List, Dict, Optional, Any, Iterable, Mapping, Tuple
import reconcile.utils.threaded as threaded
import reconcile.queries as queries

from reconcile.utils.oc import OC_Map
from reconcile.utils.defer import defer
from reconcile.utils.sharding import is_in_shard
from reconcile.status import ExitCodes


QONTRACT_INTEGRATION = 'openshift-namespaces'

NS_STATE_PRESENT = "present"
NS_STATE_ABSENT = "absent"

NS_ACTION_CREATE = "create"
NS_ACTION_DELETE = "delete"


def get_desired_state(
        namespaces: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:

    desired_state: List[Dict[str, str]] = []
    for ns in namespaces:
        state = NS_STATE_PRESENT
        if ns.get("delete"):
            state = NS_STATE_ABSENT

        desired_state.append({"cluster": ns["cluster"]["name"],
                              "namespace": ns["name"],
                              "desired_state": state})

    return desired_state


def get_shard_namespaces(namespaces: Any) \
        -> Tuple[List[Dict[str, str]], bool]:

    shard_namespaces = {}
    duplicated_ns = set()
    err = False
    for ns in namespaces:
        shard_key = f'{ns["cluster"]["name"]}/{ns["name"]}'
        if is_in_shard(shard_key):
            if shard_key not in shard_namespaces:
                shard_namespaces[shard_key] = ns
            else:
                err = True
                duplicated_ns.add(shard_key)

    for shard_key in duplicated_ns:
        logging.error(
            f"Found multiple definitions for the namespace {shard_key};"
            " Ignoring")
        del shard_namespaces[shard_key]

    return list(shard_namespaces.values()), err


def manage_namespaces(spec: Mapping[str, str],
                      oc_map: OC_Map, dry_run: bool) -> None:
    cluster = spec['cluster']
    namespace = spec['namespace']
    desired_state = spec["desired_state"]

    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return None

    act = {
        NS_ACTION_CREATE: oc.new_project,
        NS_ACTION_DELETE: oc.delete_project
    }

    exists = oc.project_exists(namespace)
    action = None
    if not exists and desired_state == NS_STATE_PRESENT:
        action = NS_ACTION_CREATE
    elif exists and desired_state == NS_STATE_ABSENT:
        action = NS_ACTION_DELETE

    if action:
        logging.info([action, cluster, namespace])
        if not dry_run:
            act[action](namespace)


def check_results(
        desired_state: Iterable[Mapping[str, str]],
        results: Iterable[Any]) -> bool:
    err = False
    for s, e in zip(desired_state, results):
        if isinstance(e, Exception):
            err = True
            msg = (
                f'cluster: {s["cluster"]}, namespace: {s["namespace"]}, '
                f'exception: {str(e)}'
            )
            logging.error(msg)
    return err


@defer
def run(dry_run: bool, thread_pool_size=10,
        internal: Optional[bool] = None, use_jump_host=True,
        defer=None):

    namespaces = queries.get_namespaces(minimal=True)
    shard_namespaces, duplicates = get_shard_namespaces(namespaces)
    desired_state = get_desired_state(shard_namespaces)

    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=shard_namespaces,
                    integration=QONTRACT_INTEGRATION,
                    settings=settings, internal=internal,
                    use_jump_host=use_jump_host,
                    thread_pool_size=thread_pool_size,
                    init_projects=True)

    defer(lambda: oc_map.cleanup())

    results = threaded.run(manage_namespaces, desired_state,
                           thread_pool_size, return_exceptions=True,
                           dry_run=dry_run, oc_map=oc_map)

    err = check_results(desired_state, results)
    if err or duplicates:
        sys.exit(ExitCodes.ERROR)
