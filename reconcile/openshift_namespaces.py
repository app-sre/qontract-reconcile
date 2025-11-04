import logging
from collections import defaultdict
from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from enum import StrEnum
from typing import Any, TypedDict

from sretoolbox.utils import threaded

import reconcile.openshift_base as ob
from reconcile.gql_definitions.common.namespaces_minimal import NamespaceV1
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.namespaces_minimal import get_namespaces_minimal
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.oc_filters import (
    filter_namespaces_by_cluster_and_namespace,
)
from reconcile.utils.oc_map import (
    OCLogMsg,
    OCMap,
    init_oc_map_from_namespaces,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.sharding import is_in_shard

QONTRACT_INTEGRATION = "openshift-namespaces"


class Action(StrEnum):
    CREATE = "create"
    DELETE = "delete"


class DesiredState(TypedDict):
    cluster: str
    namespace: str
    delete: bool


class NamespaceRuntimeError(Exception):
    pass


class NamespaceDuplicateError(Exception):
    pass


def get_namespaces(
    cluster_name: Sequence[str] | None,
    namespace_name: Sequence[str] | None,
) -> tuple[list[NamespaceV1], list[NamespaceDuplicateError]]:
    all_namespaces = get_namespaces_minimal()

    namespaces_by_shard_key = defaultdict(list)

    for namespace in all_namespaces:
        key = f"{namespace.cluster.name}/{namespace.name}"
        if is_in_shard(key):
            namespaces_by_shard_key[key].append(namespace)

    managed_namespaces = []
    duplicate_errors = []

    for key, namespaces in namespaces_by_shard_key.items():
        if len(namespaces) == 1:
            namespace = namespaces[0]
            if not namespace.managed_by_external:
                managed_namespaces.append(namespace)
        else:
            msg = f"Found multiple definitions for the namespace {key}"
            duplicate_errors.append(NamespaceDuplicateError(msg))
            logging.error(msg)

    namespaces = filter_namespaces_by_cluster_and_namespace(
        namespaces=managed_namespaces,
        cluster_names=cluster_name,
        namespace_names=namespace_name,
    )

    return namespaces, duplicate_errors


def build_desired_state(
    namespaces: Iterable[NamespaceV1],
) -> list[DesiredState]:
    return [
        DesiredState(
            cluster=namespace.cluster.name,
            namespace=namespace.name,
            delete=namespace.delete or False,
        )
        for namespace in namespaces
    ]


def manage_namespace(
    desired_state: DesiredState,
    oc_map: OCMap,
    dry_run: bool,
) -> None:
    cluster = desired_state["cluster"]
    namespace = desired_state["namespace"]

    oc = oc_map.get(cluster)
    if isinstance(oc, OCLogMsg):
        logging.log(level=oc.log_level, msg=oc.message)
        return

    act = {
        Action.CREATE: oc.new_project,
        Action.DELETE: oc.delete_project,
    }

    desired_delete = desired_state["delete"]
    current_delete = not oc.project_exists(namespace)

    if desired_delete == current_delete:
        return

    action = Action.DELETE if desired_delete else Action.CREATE

    if action == Action.CREATE and namespace.startswith("openshift-"):
        raise ValueError('cannot request a project starting with "openshift-"')

    logging.info([str(action), cluster, namespace])
    if not dry_run:
        act[action](namespace)


def build_runtime_errors(
    desired_state: Iterable[DesiredState],
    results: Iterable[Any],
) -> list[NamespaceRuntimeError]:
    return [
        NamespaceRuntimeError(
            f"cluster: {s['cluster']}, namespace: {s['namespace']}, exception: {e!s}"
        )
        for s, e in zip(desired_state, results, strict=False)
        if isinstance(e, Exception)
    ]


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    cluster_name: Sequence[str] | None = None,
    namespace_name: Sequence[str] | None = None,
    defer: Callable | None = None,
) -> None:
    namespaces, duplicate_errors = get_namespaces(cluster_name, namespace_name)
    desired_state = build_desired_state(namespaces)

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
        manage_namespace,
        desired_state,
        thread_pool_size,
        return_exceptions=True,
        dry_run=dry_run,
        oc_map=oc_map,
    )

    runtime_errors = build_runtime_errors(desired_state, results)
    errors = runtime_errors + duplicate_errors
    if errors:
        raise ExceptionGroup("Reconcile errors occurred", errors)
