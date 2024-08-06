import logging
import sys
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from typing import Any

from sretoolbox.utils import threaded

import reconcile.openshift_base as ob
from reconcile.gql_definitions.common.namespaces_minimal import NamespaceV1
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.namespaces_minimal import get_namespaces_minimal
from reconcile.utils.defer import defer
from reconcile.utils.oc_filters import filter_namespaces_by_cluster_and_namespace
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.sharding import is_in_shard

QONTRACT_INTEGRATION = "openshift-namespaces"

NS_STATE_PRESENT = "present"
NS_STATE_ABSENT = "absent"

NS_ACTION_CREATE = "create"
NS_ACTION_DELETE = "delete"


DUPLICATES_LOG_MSG = "Found multiple definitions for the namespace {key}"


def get_desired_state(namespaces: Iterable[NamespaceV1]) -> list[dict[str, str]]:
    desired_state: list[dict[str, str]] = []
    for ns in namespaces:
        state = NS_STATE_PRESENT
        if ns.delete:
            state = NS_STATE_ABSENT

        desired_state.append({
            "cluster": ns.cluster.name,
            "namespace": ns.name,
            "desired_state": state,
        })

    return desired_state


def get_shard_namespaces(
    namespaces: Iterable[NamespaceV1],
) -> tuple[list[NamespaceV1], bool]:
    # Structure holding duplicates by namespace key
    duplicates: dict[str, list[NamespaceV1]] = {}
    # namespace filtered list without duplicates
    filtered_ns: dict[str, NamespaceV1] = {}

    err = False
    for ns in namespaces:
        key = f"{ns.cluster.name}/{ns.name}"

        if is_in_shard(key):
            if key not in filtered_ns:
                filtered_ns[key] = ns
            else:
                # Duplicated NS
                dupe_list_by_key = duplicates.setdefault(key, [])
                dupe_list_by_key.append(ns)

    for key, dupe_list in duplicates.items():
        dupe_list.append(filtered_ns[key])
        delete_flags = (
            [ns.delete for ns in dupe_list_by_key] if dupe_list_by_key else []
        )

        if len(set(delete_flags)) > 1:
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


def manage_namespaces(spec: Mapping[str, str], oc_map: OCMap, dry_run: bool) -> None:
    cluster = spec["cluster"]
    namespace = spec["namespace"]
    desired_state = spec["desired_state"]

    oc = oc_map.get(cluster)
    if isinstance(oc, OCLogMsg):
        logging.log(level=oc.log_level, msg=oc.message)
        return None

    act = {NS_ACTION_CREATE: oc.new_project, NS_ACTION_DELETE: oc.delete_project}

    exists = oc.project_exists(namespace)
    action = None
    if not exists and desired_state == NS_STATE_PRESENT:
        if namespace.startswith("openshift-"):
            raise ValueError('cannot request a project starting with "openshift-"')
        action = NS_ACTION_CREATE
    elif exists and desired_state == NS_STATE_ABSENT:
        action = NS_ACTION_DELETE

    if action:
        logging.info([action, cluster, namespace])
        if not dry_run:
            act[action](namespace)


def check_results(
    desired_state: Iterable[Mapping[str, str]], results: Iterable[Any]
) -> bool:
    err = False
    for s, e in zip(desired_state, results, strict=False):
        if isinstance(e, Exception):
            err = True
            msg = (
                f'cluster: {s["cluster"]}, namespace: {s["namespace"]}, '
                f"exception: {e!s}"
            )
            logging.error(msg)
    return err


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    cluster_name: Sequence[str] | None = None,
    namespace_name: Sequence[str] | None = None,
    defer: Callable | None = None,
) -> None:
    all_namespaces = get_namespaces_minimal()
    shard_namespaces, duplicates = get_shard_namespaces(all_namespaces)
    namespaces = filter_namespaces_by_cluster_and_namespace(
        namespaces=shard_namespaces,
        cluster_names=cluster_name,
        namespace_names=namespace_name,
    )

    desired_state = get_desired_state(namespaces)

    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    oc_map = init_oc_map_from_namespaces(
        namespaces=namespaces,
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        init_projects=True,
    )

    if defer:
        defer(oc_map.cleanup)

    ob.publish_cluster_desired_metrics_from_state(
        desired_state, QONTRACT_INTEGRATION, "Namespace"
    )

    results = threaded.run(
        manage_namespaces,
        desired_state,
        thread_pool_size,
        return_exceptions=True,
        dry_run=dry_run,
        oc_map=oc_map,
    )

    err = check_results(desired_state=desired_state, results=results)
    if err or duplicates:
        sys.exit(ExitCodes.ERROR)
