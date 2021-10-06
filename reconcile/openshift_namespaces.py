import logging

from typing import List, Dict, Optional, Tuple, Any
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
        namespaces: List[Dict[str, Any]]) -> List[Dict[str, str]]:

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
    all_namespaces = queries.get_namespaces()
    namespaces = {}
    to_be_ignored = []
    for namespace in all_namespaces:
        shard_key = f'{namespace["cluster"]["name"]}/{namespace["name"]}'
        if is_in_shard(shard_key):
            if shard_key not in namespaces:
                namespaces[shard_key] = namespace
            else:
                to_be_ignored.append(shard_key)
    for shard_key in to_be_ignored:
        logging.debug(
            f"Found multiple definitions for the namespace {shard_key};"
            " Ignoring")
        del namespaces[shard_key]

    return list(namespaces.values())


def check_ns_exists(spec: Dict[str, str],
                    oc_map: OC_Map) -> Tuple[Dict[str, str], Optional[bool]]:
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


def manage_projects(spec: Dict[str, str], oc_map: OC_Map, action: str) -> None:
    cluster = spec['cluster']
    namespace = spec['namespace']

    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return None

    if action == NS_ACTION_CREATE:
        try:
            oc.new_project(namespace)
        except StatusCodeError as e:
            msg = (
                f'cluster: {cluster}, namespace: {namespace}, '
                f'exception: {str(e)}'
            )
            logging.error(msg)
    elif action == NS_ACTION_DELETE:
        oc.delete_project(namespace)


@defer
def run(dry_run: bool, thread_pool_size: int = 10,
        internal: Optional[bool] = None, use_jump_host: bool = True,
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

    ns_to_create = []
    ns_to_delete = []
    for ns, exists in results:
        if exists is None:
            continue
        elif not exists and ns["state"] == NS_STATUS_PRESENT:
            logging.info(['create', ns['cluster'], ns['namespace']])
            ns_to_create.append(ns)

        elif exists and ns["state"] == NS_STATUS_ABSENT:
            logging.info(['delete', ns['cluster'], ns['namespace']])
            ns_to_delete.append(ns)

    if not dry_run:
        threaded.run(manage_projects, ns_to_create, thread_pool_size,
                     oc_map=oc_map, action=NS_ACTION_CREATE)

        threaded.run(manage_projects, ns_to_delete, thread_pool_size,
                     oc_map=oc_map, action=NS_ACTION_DELETE)
