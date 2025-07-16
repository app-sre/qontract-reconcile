import contextlib
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import reconcile.openshift_base as ob
from reconcile import queries
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

ROLES_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      org_username
      github_username
    }
    bots {
      openshift_serviceaccount
    }
    access {
      namespace {
        name
        clusterAdmin
        managedRoles
        delete
        cluster {
          name
          auth {
            service
          }
        }
      }
      role
    }
    expirationDate
  }
}
"""


QONTRACT_INTEGRATION = "openshift-rolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)


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
    gqlapi = gql.get_api()
    roles_query_result = gqlapi.query(ROLES_QUERY)
    if not roles_query_result:
        return []
    roles: Sequence[Mapping[str, Any]] = expiration.filter(roles_query_result["roles"])
    users_desired_state = []
    for role in roles:
        permissions = [
            {
                "cluster": a["namespace"]["cluster"],
                "namespace": a["namespace"],
                "role": a["role"],
            }
            for a in role["access"] or []
            if a["namespace"]
            and a["role"]
            and a["namespace"].get("managedRoles")
            and not ob.is_namespace_deleted(a["namespace"])
        ]
        if not permissions:
            continue

        service_accounts = [
            bot["openshift_serviceaccount"]
            for bot in role["bots"]
            if bot.get("openshift_serviceaccount")
        ]

        for permission in permissions:
            cluster_info = permission["cluster"]
            cluster = cluster_info["name"]
            namespace_info = permission["namespace"]
            perm_namespace_name = namespace_info["name"]
            privileged = namespace_info.get("clusterAdmin") or False
            if not is_in_shard(f"{cluster}/{perm_namespace_name}"):
                continue
            if oc_map and not oc_map.get(cluster):
                continue

            # get username keys based on used IDPs
            user_keys = ob.determine_user_keys_for_access(
                cluster,
                cluster_info.get("auth") or [],
                enforced_user_keys=enforced_user_keys,
            )
            # create user rolebindings for user * user_keys
            for user in role.get("users") or []:
                for username in {user.get(key) for key in user_keys}:
                    if not username:
                        continue
                    # used by openshift-users and github integrations
                    # this is just to simplify things a bit on the their side
                    users_desired_state.append({"cluster": cluster, "user": username})
                    if ri is None:
                        continue
                    oc_resource, resource_name = construct_user_oc_resource(
                        permission["role"], username
                    )
                    with contextlib.suppress(ResourceKeyExistsError):
                        # a user may have a Role assigned to them
                        # from multiple app-interface roles
                        ri.add_desired(
                            cluster,
                            perm_namespace_name,
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
                    permission["role"], sa_namespace_name, sa_name
                )
                with contextlib.suppress(ResourceKeyExistsError):
                    # a ServiceAccount may have a Role assigned to it
                    # from multiple app-interface roles
                    ri.add_desired(
                        cluster,
                        perm_namespace_name,
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
        namespace_info
        for namespace_info in queries.get_namespaces()
        if namespace_info.get("managedRoles")
        and is_in_shard(
            f"{namespace_info['cluster']['name']}/" + f"{namespace_info['name']}"
        )
        and not ob.is_namespace_deleted(namespace_info)
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
