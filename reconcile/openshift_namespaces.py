import logging

from typing import List, Dict, Optional, Tuple, Any, Iterable, Mapping
import reconcile.utils.threaded as threaded
import reconcile.queries as queries

from reconcile.utils.oc import OC_Map
from reconcile.utils.oc import StatusCodeError
from reconcile.utils.defer import defer
from reconcile.utils.sharding import is_in_shard


QONTRACT_INTEGRATION = 'openshift-namespaces'

NS_STATUS_PRESENT = "present"
NS_STATUS_ABSENT = "absent"

NS_ACTION_DELETE = "delete"
NS_ACTION_CREATE = "create"


def get_desired_state(
        namespaces: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:

    desired_state: List[Dict[str, str]] = []
    for namespace in namespaces:
        state = NS_STATUS_PRESENT
        if namespace.get("delete"):
            state = NS_STATUS_ABSENT

        desired_state.append({"cluster": namespace["cluster"]["name"],
                              "namespace": namespace["name"],
                              "state": state})

    return desired_state


def get_shard_namespaces() -> List[Dict[str, str]]:
    all_namespaces = queries.get_namespaces(minimal=True)
    namespaces = {}
    duplicated_ns = set()
    for ns in all_namespaces:
        shard_key = f'{ns["cluster"]["name"]}/{ns["name"]}'
        if is_in_shard(shard_key):
            if shard_key not in namespaces:
                namespaces[shard_key] = ns
            else:
                duplicated_ns.add(shard_key)

    for shard_key in duplicated_ns:
        logging.debug(
            f"Found multiple definitions for the namespace {shard_key};"
            " Ignoring")
        del namespaces[shard_key]

    return list(namespaces.values())


def check_ns_exists(spec: Mapping[str, str],
                    oc_map: OC_Map) -> Tuple[Mapping[str, str], Any]:
    cluster = spec['cluster']
    namespace = spec['namespace']
    try:
        exists = oc_map.get(cluster).project_exists(namespace)
        return spec, exists
    except StatusCodeError as e:
        msg = (
            f'cluster: {cluster}, namespace: {namespace}, exception: {str(e)}'
        )
        logging.error(msg)

    return spec, None


def manage_projects(spec: Mapping[str, str],
                    oc_map: OC_Map, dry_run: bool) -> None:
    cluster = spec['cluster']
    namespace = spec['namespace']
    action = spec["action"]

    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return None

    if action == NS_ACTION_CREATE:
        try:
            logging.info(['create', cluster, namespace])
            if not dry_run:
                oc.new_project(namespace)
        except StatusCodeError as e:
            msg = (
                f'cluster: {cluster}, namespace: {namespace}, '
                f'exception: {str(e)}'
            )
            logging.error(msg)

    elif action == NS_ACTION_DELETE:
        logging.info(['create', cluster, namespace])
        if not dry_run:
            oc.delete_project(namespace)


@defer
def run(dry_run: bool, thread_pool_size=10,
        internal: Optional[bool] = None, use_jump_host=True,
        defer=None):

    namespaces = get_shard_namespaces()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces,
                    integration=QONTRACT_INTEGRATION,
                    settings=settings, internal=internal,
                    use_jump_host=use_jump_host,
                    thread_pool_size=thread_pool_size,
                    init_projects=True)

    defer(lambda: oc_map.cleanup())

    desired_state = get_desired_state(namespaces)

    results = threaded.run(check_ns_exists, desired_state, thread_pool_size,
                           oc_map=oc_map)

    specs = []
    for spec, exists in results:
        if exists is None:
            continue
        elif not exists and spec["state"] == NS_STATUS_PRESENT:
            spec["action"] = NS_ACTION_CREATE
        elif exists and spec["state"] == NS_STATUS_ABSENT:
            spec["action"] = NS_ACTION_DELETE
        else:
            continue
        specs.append(spec)

    threaded.run(manage_projects, specs, thread_pool_size,
                 dry_run=dry_run, oc_map=oc_map)
