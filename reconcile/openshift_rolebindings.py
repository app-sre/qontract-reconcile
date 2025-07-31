import contextlib
from dataclasses import dataclass
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from reconcile.gql_definitions.common.openshift_roles import (
    RoleV1,
    query as openshift_roles_query,
    ClusterV1,
    NamespaceV1,
)
import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.typed_queries.namespaces import get_namespaces
from reconcile.typed_queries.app_interface_roles import get_app_interface_roles
from reconcile.utils import (
    expiration,
    gql,
)
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    ResourceInventory,
    ResourceKeyExistsError,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard


QONTRACT_INTEGRATION = "openshift-rolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)


@dataclass
class Permission:
    role: str
    namespace: NamespaceV1
    cluster: ClusterV1

def construct_user_oc_resource(role: str, user: str) -> tuple[OR, str]:
    name = f"{role}-{user}"
    body = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": name},
        "roleRef": {"kind": "ClusterRole", "name": role},
        "subjects": [{"kind": "User", "name": user}],
    }
    return (
        OR(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
        ),
        name,
    )


def construct_sa_oc_resource(role: str, namespace: str, sa_name: str) -> tuple[OR, str]:
    name = f"{role}-{namespace}-{sa_name}"
    body = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": name},
        "roleRef": {"kind": "ClusterRole", "name": role},
        "subjects": [
            {"kind": "ServiceAccount", "name": sa_name, "namespace": namespace}
        ],
    }
    return (
        OR(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
        ),
        name,
    )

def fetch_desired_state(
    ri: ResourceInventory | None,
    oc_map: ob.ClusterMap | None,
    enforced_user_keys: list[str] | None = None,
) -> list[dict[str, str]]:
    roles: list[RoleV1] = expiration.filter(get_app_interface_roles())
    users_desired_state = []
    for role in roles:
        permissions: list[Permission] = [
            Permission(
                role=access.role,
                namespace=access.namespace,
                cluster=access.namespace.cluster,
            )
            for access in role.access or []
            if access.namespace
            and access.role
            and access.namespace.managed_roles
            and not ob.is_namespace_deleted(access.namespace.dict(by_alias=True))
        ]
        if not permissions:
            continue

        service_accounts = [
            bot.openshift_serviceaccount
            for bot in role.bots
            if bot.openshift_serviceaccount
        ]

        for permission in permissions:
            cluster_name = permission.cluster.name
            namespace_name = permission.namespace.name
            privileged = permission.namespace.cluster_admin or False
            if not is_in_shard(f"{cluster_name}/{namespace_name}"):
                continue
            if oc_map and not oc_map.get(cluster=cluster_name):
                continue

            # get username keys based on used IDPs
            user_keys = ob.determine_user_keys_for_access(
                cluster_name,
                permission.cluster.auth,
                enforced_user_keys=enforced_user_keys,
            )
            # create user rolebindings for user * user_keys
            for user in role.users:
                for username in {getattr(user, user_key) for user_key in user_keys}:
                    if not username:
                        continue
                    # used by openshift-users and github integrations
                    # this is just to simplify things a bit on the their side
                    users_desired_state.append({"cluster": cluster_name, "user": username})
                    if ri is None:
                        continue
                    oc_resource, resource_name = construct_user_oc_resource(
                        permission.role, username
                    )
                    with contextlib.suppress(ResourceKeyExistsError):
                        # a user may have a Role assigned to them
                        # from multiple app-interface roles
                        ri.add_desired(
                            cluster_name,
                            namespace_name,
                            "RoleBinding.rbac.authorization.k8s.io",
                            resource_name,
                            oc_resource,
                            privileged=privileged,
                        )

            for sa in service_accounts:
                if ri is None:
                    continue
                sa_namespace_name, sa_name = sa.split("/")
                oc_resource, resource_name = construct_sa_oc_resource(
                    permission.role, sa_namespace_name, sa_name
                )
                with contextlib.suppress(ResourceKeyExistsError):
                    # a ServiceAccount may have a Role assigned to it
                    # from multiple app-interface roles
                    ri.add_desired(
                        cluster_name,
                        namespace_name,
                        "RoleBinding.rbac.authorization.k8s.io",
                        resource_name,
                        oc_resource,
                        privileged=privileged,
                    )
    return users_desired_state

@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    namespaces = [
        namespace.dict(by_alias=True,exclude={"openshift_resources"})
        for namespace in get_namespaces()
        if namespace.managed_roles
        and is_in_shard(
            f"{namespace.cluster.name}/{namespace.name}"
        )
        and not ob.is_namespace_deleted(namespace.dict(by_alias=True))
    ]
    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["RoleBinding.rbac.authorization.k8s.io"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    if defer:
        defer(oc_map.cleanup)
    fetch_desired_state(ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
