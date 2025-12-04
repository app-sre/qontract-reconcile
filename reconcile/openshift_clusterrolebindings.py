import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

from pydantic.main import BaseModel

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    BotV1,
    ClusterV1,
    RoleV1,
    UserV1,
)
from reconcile.typed_queries.app_interface_clusterroles import (
    get_app_interface_clusterroles,
)
from reconcile.utils import (
    expiration,
)
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    ResourceInventory,
)
from reconcile.utils.semver_helper import make_semver

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
      cluster {
        name
        auth {
          service
        }
      }
      clusterRole
    }
    expirationDate
  }
}
"""


QONTRACT_INTEGRATION = "openshift-clusterrolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
NAMESPACE_CLUSTER_SCOPE = "cluster"


class OCResource(BaseModel, arbitrary_types_allowed=True):
    resource: OR
    resource_name: str


@dataclass
class ServiceAccountSpec:
    sa_namespace_name: str
    sa_name: str

    @classmethod
    def create_sa_spec(cls, bots: list[BotV1] | None) -> list[Self]:
        return [
            cls(
                sa_namespace_name=full_service_account[0],
                sa_name=full_service_account[1],
            )
            for bot in bots or []
            if bot.openshift_serviceaccount
            and (full_service_account := bot.openshift_serviceaccount.split("/"))
            and len(full_service_account) == 2
        ]


class ClusterRoleBindingSpec(
    BaseModel, validate_by_alias=True, arbitrary_types_allowed=True
):
    cluster_role_name: str
    cluster: ClusterV1
    usernames: set[str]
    openshift_service_accounts: list[ServiceAccountSpec]

    @classmethod
    def create_cluster_role_binding_specs(cls, cluster_role: RoleV1) -> list[Self]:
        cluster_role_binding_spec = [
            cls(
                cluster_role_name=access.cluster_role,
                cluster=access.cluster,
                usernames=ClusterRoleBindingSpec.get_usernames_from_users_and_cluster(
                    cluster_role.users, access.cluster
                ),
                openshift_service_accounts=ServiceAccountSpec.create_sa_spec(
                    cluster_role.bots
                ),
            )
            for access in cluster_role.access or []
            if access.cluster and access.cluster_role
        ]
        return cluster_role_binding_spec

    def get_oc_resources(self) -> list[OCResource]:
        user_oc_resources = [
            self.construct_user_oc_resource(username) for username in self.usernames
        ]
        sa_oc_resources = [
            self.construct_sa_oc_resource(sa.sa_namespace_name, sa.sa_name)
            for sa in self.openshift_service_accounts
        ]
        return user_oc_resources + sa_oc_resources

    def construct_user_oc_resource(self, user: str) -> OCResource:
        name = f"{self.cluster_role_name}-{user}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": name},
            "roleRef": {"name": self.cluster_role_name, "kind": "ClusterRole"},
            "subjects": [{"kind": "User", "name": user}],
        }
        return OCResource(
            resource=OR(
                body,
                QONTRACT_INTEGRATION,
                QONTRACT_INTEGRATION_VERSION,
                error_details=name,
            ),
            resource_name=name,
        )

    def construct_sa_oc_resource(
        self, sa_namespace_name: str, sa_name: str
    ) -> OCResource:
        name = f"{self.cluster_role_name}-{sa_namespace_name}-{sa_name}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": name},
            "roleRef": {"name": self.cluster_role_name, "kind": "ClusterRole"},
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": sa_name,
                    "namespace": sa_namespace_name,
                }
            ],
        }
        return OCResource(
            resource=OR(
                body,
                QONTRACT_INTEGRATION,
                QONTRACT_INTEGRATION_VERSION,
                error_details=name,
            ),
            resource_name=name,
        )

    @staticmethod
    def get_usernames_from_users_and_cluster(
        users: list[UserV1], cluster: ClusterV1
    ) -> set[str]:
        auth_dict = [auth.model_dump(by_alias=True) for auth in cluster.auth]
        user_keys = ob.determine_user_keys_for_access(cluster.name, auth_dict)
        return {
            name
            for user in users or []
            for user_key in user_keys or []
            if (name := getattr(user, user_key, None))
        }


def fetch_desired_state(
    ri: ResourceInventory | None, allowed_clusters: set[str] | None = None
) -> None:
    if allowed_clusters is not None and not allowed_clusters:
        return None
    cluster_roles: list[RoleV1] = expiration.filter(get_app_interface_clusterroles())
    clusters_to_check = allowed_clusters or set()
    cluster_role_binding_specs = [
        cluster_role_binding_spec
        for cluster_role in cluster_roles
        for cluster_role_binding_spec in ClusterRoleBindingSpec.create_cluster_role_binding_specs(
            cluster_role
        )
        if cluster_role_binding_spec.cluster.name in clusters_to_check
    ]
    for cluster_role_binding_spec in cluster_role_binding_specs:
        if ri is None:
            continue
        for oc_resource in cluster_role_binding_spec.get_oc_resources():
            if not ri.get_desired(
                cluster_role_binding_spec.cluster.name,
                NAMESPACE_CLUSTER_SCOPE,
                "ClusterRoleBinding.rbac.authorization.k8s.io",
                oc_resource.resource_name,
            ):
                ri.add_desired(
                    cluster=cluster_role_binding_spec.cluster.name,
                    namespace=NAMESPACE_CLUSTER_SCOPE,
                    resource_type="ClusterRoleBinding.rbac.authorization.k8s.io",
                    name=oc_resource.resource_name,
                    value=oc_resource.resource,
                )


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    clusters = [
        cluster_info
        for cluster_info in queries.get_clusters()
        if cluster_info.get("managedClusterRoles")
        and cluster_info.get("automationToken")
    ]
    ri, oc_map = ob.fetch_current_state(
        clusters=clusters,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["ClusterRoleBinding.rbac.authorization.k8s.io"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    if defer:
        defer(oc_map.cleanup)
    fetch_desired_state(ri, set(oc_map.clusters()))
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
