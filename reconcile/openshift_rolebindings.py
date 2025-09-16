import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

from pydantic.main import BaseModel

import reconcile.openshift_base as ob
from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    BotV1,
    ClusterV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.gql_definitions.common.namespaces import NamespaceV1 as CommonNamespaceV1
from reconcile.typed_queries.app_interface_roles import get_app_interface_roles
from reconcile.typed_queries.namespaces import get_namespaces
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
from reconcile.utils.sharding import is_in_shard

QONTRACT_INTEGRATION = "openshift-rolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)


class OCResource(BaseModel):
    resource: OR
    resource_name: str
    privileged: bool

    class Config:
        arbitrary_types_allowed = True


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


class RoleBindingSpec(BaseModel):
    role_name: str
    role_kind: str
    namespace: NamespaceV1
    cluster: ClusterV1
    privileged: bool
    usernames: set[str]
    openshift_service_accounts: list[ServiceAccountSpec]

    class Config:
        arbitrary_types_allowed = True

    def get_users_desired_state(self) -> list[dict[str, str]]:
        return [
            {"cluster": self.cluster.name, "user": username}
            for username in self.usernames
        ]

    @classmethod
    def create_role_binding_spec(
        cls,
        access: AccessV1,
        users: list[UserV1] | None = None,
        enforced_user_keys: list[str] | None = None,
        bots: list[BotV1] | None = None,
        support_role_ref: bool = False,
    ) -> Self | None:
        if not access.namespace:
            return None
        if not (access.role or access.cluster_role):
            return None
        privileged = access.namespace.cluster_admin or False
        auth_dict = [auth.dict(by_alias=True) for auth in access.namespace.cluster.auth]
        usernames = RoleBindingSpec.get_usernames_from_users(
            users,
            ob.determine_user_keys_for_access(
                access.namespace.cluster.name,
                auth_dict,
                enforced_user_keys,
            ),
        )
        service_accounts = ServiceAccountSpec.create_sa_spec(bots) if bots else []
        role_kind = "Role" if access.role and support_role_ref else "ClusterRole"
        return cls(
            role_name=access.role or access.cluster_role,
            role_kind=role_kind,
            namespace=access.namespace,
            cluster=access.namespace.cluster,
            privileged=privileged,
            usernames=usernames,
            openshift_service_accounts=service_accounts,
        )

    @classmethod
    def create_rb_specs_from_role(
        cls,
        role: RoleV1,
        enforced_user_keys: list[str] | None = None,
        support_role_ref: bool = False,
    ) -> list[Self]:
        rolebinding_spec_list = [
            role_binding_spec
            for access in role.access or []
            if (
                access.namespace
                and is_valid_namespace(access.namespace)
                and (
                    role_binding_spec := cls.create_role_binding_spec(
                        access,
                        role.users,
                        enforced_user_keys,
                        role.bots,
                        support_role_ref,
                    )
                )
            )
        ]
        return rolebinding_spec_list

    @staticmethod
    def get_usernames_from_users(
        users: list[UserV1] | None = None, user_keys: list[str] | None = None
    ) -> set[str]:
        return {
            name
            for user in users or []
            for user_key in user_keys or []
            if (name := getattr(user, user_key, None))
        }

    def construct_user_oc_resource(self, user: str) -> OCResource:
        name = f"{self.role_name}-{user}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": name},
            "roleRef": {"kind": self.role_kind, "name": self.role_name},
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
            privileged=self.privileged,
        )

    def get_oc_resources(self) -> list[OCResource]:
        user_oc_resources = [
            self.construct_user_oc_resource(username) for username in self.usernames
        ]
        sa_oc_resources = [
            self.construct_sa_oc_resource(sa.sa_namespace_name, sa.sa_name)
            for sa in self.openshift_service_accounts
        ]
        return user_oc_resources + sa_oc_resources

    def construct_sa_oc_resource(
        self, sa_namespace_name: str, sa_name: str
    ) -> OCResource:
        name = f"{self.role_name}-{sa_namespace_name}-{sa_name}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": name},
            "roleRef": {"kind": self.role_kind, "name": self.role_name},
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
            privileged=self.privileged,
        )


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
    support_role_ref: bool = False,
    enforced_user_keys: list[str] | None = None,
    allowed_clusters: set[str] | None = None,
) -> list[dict[str, str]]:
    if allowed_clusters is not None and not allowed_clusters:
        return []
    roles: list[RoleV1] = expiration.filter(get_app_interface_roles())
    users_desired_state: list[dict[str, str]] = []
    for role in roles:
        rolebindings: list[RoleBindingSpec] = RoleBindingSpec.create_rb_specs_from_role(
            role, enforced_user_keys, support_role_ref
        )
        if allowed_clusters is not None:
            rolebindings = [
                rolebinding
                for rolebinding in rolebindings
                if rolebinding.cluster.name in allowed_clusters
            ]
        for rolebinding in rolebindings:
            users_desired_state.extend(rolebinding.get_users_desired_state())
            if ri is None:
                continue
            for oc_resource in rolebinding.get_oc_resources():
                if not ri.get_desired(
                    rolebinding.cluster.name,
                    rolebinding.namespace.name,
                    "RoleBinding.rbac.authorization.k8s.io",
                    oc_resource.resource_name,
                ):
                    ri.add_desired_resource(
                        cluster=rolebinding.cluster.name,
                        namespace=rolebinding.namespace.name,
                        resource=oc_resource.resource,
                        privileged=oc_resource.privileged,
                    )
    return users_desired_state


def is_valid_namespace(namespace: NamespaceV1 | CommonNamespaceV1) -> bool:
    return (
        bool(namespace.managed_roles)
        and is_in_shard(f"{namespace.cluster.name}/{namespace.name}")
        and not ob.is_namespace_deleted(namespace.dict(by_alias=True))
    )


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    support_role_ref: bool = False,
    defer: Callable | None = None,
) -> None:
    namespaces = [
        namespace.dict(by_alias=True, exclude={"openshift_resources"})
        for namespace in get_namespaces()
        if is_valid_namespace(namespace)
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
    fetch_desired_state(ri, support_role_ref, allowed_clusters=set(oc_map.clusters()))
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
