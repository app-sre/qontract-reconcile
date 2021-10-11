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


DUPLICATES_LOG_MSG = "Found multiple definitions for the namespace {key}"

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


def get_shard_namespaces(namespaces: Any) -> List[Any]:
    shard_namespaces = []
    for ns in namespaces:
        shard_key = f'{ns["cluster"]["name"]}/{ns["name"]}'
        if is_in_shard(shard_key):
            shard_namespaces.append(ns)

    return shard_namespaces


def manage_duplicated_namespaces(namespaces: Any) \
        -> Tuple[List[Dict[str, str]], bool]:

    # Structure holding duplicates by namespace key
    duplicated_ns: Dict[str, Iterable[Mapping[str, str]]] = {}
    # namespace filtered list without duplicates
    filtered_ns: Dict[str, Dict[str, str]] = {}

    err = False
    for ns in namespaces:
        key = f'{ns["cluster"]["name"]}/{ns["name"]}'

        if key not in filtered_ns:
            filtered_ns[key] = ns
        else:
            # Duplicated NS
            d_list = duplicated_ns.setdefault(key, [])
            d_list.append(ns)

    for key in duplicated_ns:
        dupe_ns_list = duplicated_ns[key]
        dupe_ns_list.append(filtered_ns[key])
        deletes_in_list = [ns["delete"] for ns in dupe_ns_list]

        if len(set(deletes_in_list)) > 1:
            # If true only some definitions in list have the delete flag.
            # this case will generate an error
            err = True
            # Remove the namespace found from the filtered list
            del filtered_ns[key]
            logging.error(DUPLICATES_LOG_MSG.format(key=key))
        else:
            # If all namespaces have the same delete option
            # The action will be performaed
            logging.debug(DUPLICATES_LOG_MSG.format(key=key))

    return list(filtered_ns.values()), err


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

    all_namespaces = queries.get_namespaces(minimal=True)
    namespaces, duplicates = manage_duplicated_namespaces(all_namespaces)

    shard_namespaces = get_shard_namespaces(namespaces)
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
