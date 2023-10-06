import sys

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.utils import (
    expiration,
    gql,
)
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceKeyExistsError
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


def construct_user_oc_resource(role, user):
    name = f"{role}-{user}"
    body = {
        "apiVersion": "authorization.openshift.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": name},
        "roleRef": {"name": role},
        "subjects": [{"kind": "User", "name": user}],
    }
    return (
        OR(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
        ),
        name,
    )


def construct_sa_oc_resource(role, namespace, sa_name):
    name = f"{role}-{namespace}-{sa_name}"
    body = {
        "apiVersion": "authorization.openshift.io/v1",
        "kind": "RoleBinding",
        "metadata": {"name": name},
        "roleRef": {"name": role},
        "subjects": [
            {"kind": "ServiceAccount", "name": sa_name, "namespace": namespace}
        ],
        "userNames": [f"system:serviceaccount:{namespace}:{sa_name}"],
    }
    return (
        OR(
            body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION, error_details=name
        ),
        name,
    )


def fetch_desired_state(ri, oc_map, enforced_user_keys=None):
    gqlapi = gql.get_api()
    roles: list[dict] = expiration.filter(gqlapi.query(ROLES_QUERY)["roles"])
    users_desired_state = []
    for role in roles:
        permissions = [
            {
                "cluster": a["namespace"]["cluster"],
                "namespace": a["namespace"],
                "role": a["role"],
            }
            for a in role["access"] or []
            if None not in [a["namespace"], a["role"]]
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
                cluster, cluster_info["auth"], enforced_user_keys=enforced_user_keys
            )
            # create user rolebindings for user * user_keys
            for user in role["users"]:
                for username in {user[user_key] for user_key in user_keys}:
                    # used by openshift-users and github integrations
                    # this is just to simplify things a bit on the their side
                    users_desired_state.append({"cluster": cluster, "user": username})
                    if ri is None:
                        continue
                    oc_resource, resource_name = construct_user_oc_resource(
                        permission["role"], username
                    )
                    try:
                        ri.add_desired(
                            cluster,
                            perm_namespace_name,
                            "RoleBinding.authorization.openshift.io",
                            resource_name,
                            oc_resource,
                            privileged=privileged,
                        )
                    except ResourceKeyExistsError:
                        # a user may have a Role assigned to them
                        # from multiple app-interface roles
                        pass
            for sa in service_accounts:
                if ri is None:
                    continue
                sa_namespace_name, sa_name = sa.split("/")
                oc_resource, resource_name = construct_sa_oc_resource(
                    permission["role"], sa_namespace_name, sa_name
                )
                try:
                    ri.add_desired(
                        cluster,
                        perm_namespace_name,
                        "RoleBinding.authorization.openshift.io",
                        resource_name,
                        oc_resource,
                        privileged=privileged,
                    )
                except ResourceKeyExistsError:
                    # a ServiceAccount may have a Role assigned to it
                    # from multiple app-interface roles
                    pass

    return users_desired_state


@defer
def run(dry_run, thread_pool_size=10, internal=None, use_jump_host=True, defer=None):
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
        override_managed_types=["RoleBinding.authorization.openshift.io"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    defer(oc_map.cleanup)
    fetch_desired_state(ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
