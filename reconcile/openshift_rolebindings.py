import contextlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Optional

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
from reconcile.utils.oc import OCCli
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import (
    ResourceInventory,
    ResourceKeyExistsError,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard

QONTRACT_INTEGRATION = "openshift-rolebindings"
COMMON_CLUSTER_ROLES = ["view", "edit", "admin", "tekton-trigger-access"]
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

    @staticmethod
    def create_sa_spec(bots: list[BotV1] | None) -> list["ServiceAccountSpec"]:
        return [
            ServiceAccountSpec(
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
    username_list: set[str]
    openshift_client: OCCli | None = None
    openshift_service_accounts: list[ServiceAccountSpec]

    class Config:
        arbitrary_types_allowed = True

    def get_users_desired_state(self) -> list[dict[str, str]]:
        return [
            {"cluster": self.cluster.name, "user": username}
            for username in self.username_list
        ]

    @staticmethod
    def create_role_binding_spec(
        access: AccessV1,
        oc_map: ob.ClusterMap | None = None,
        users: list[UserV1] | None = None,
        enforced_user_keys: list[str] | None = None,
        bots: list[BotV1] | None = None,
    ) -> Optional["RoleBindingSpec"]:
        if not access.namespace:
            return None
        if not (access.role or access.cluster_role):
            return None
        privileged = access.namespace.cluster_admin or False
        if oc_map:
            openshift_client = oc_map.get(
                access.namespace.cluster.name, privileged=privileged
            )
            if not openshift_client:
                return None
        else:
            openshift_client = None
        username_list = RoleBindingSpec.get_usernames_from_role(
            users,
            ob.determine_user_keys_for_access(
                access.namespace.cluster.name,
                access.namespace.cluster.auth,
                enforced_user_keys,
            ),
        )
        service_accounts = ServiceAccountSpec.create_sa_spec(bots) if bots else []
        return RoleBindingSpec(
            role_name=access.role or access.cluster_role,
            role_kind="Role" if access.role else "ClusterRole",
            namespace=access.namespace,
            cluster=access.namespace.cluster,
            privileged=privileged,
            username_list=username_list,
            openshift_client=openshift_client,
            openshift_service_accounts=service_accounts,
        )

    @staticmethod
    def create_rb_specs_from_role(
        role: RoleV1,
        oc_map: ob.ClusterMap | None = None,
        enforced_user_keys: list[str] | None = None,
    ) -> list["RoleBindingSpec"]:
        return [
            role_binding_spec
            for access in role.access or []
            if access.namespace and is_valid_namespace(access.namespace)
            if (
                role_binding_spec := RoleBindingSpec.create_role_binding_spec(
                    access, oc_map, role.users, enforced_user_keys, role.bots
                )
            )
        ]

    @staticmethod
    def get_usernames_from_role(
        users: list[UserV1] | None = None, user_keys: list[str] | None = None
    ) -> set[str]:
        return {
            getattr(user, user_key)
            for user in users or []
            for user_key in user_keys or []
            if hasattr(user, user_key)
        }

    def construct_user_oc_resource(
        self, user: str, force_cluster_role_ref: bool
    ) -> OCResource:
        name = f"{self.role_name}-{user}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {"name": name},
            "roleRef": {"kind": self.role_kind, "name": self.role_name},
            "subjects": [{"kind": "User", "name": user}],
        }
        # if role does not exist use ClusterRole (will be cleaned up later)
        if force_cluster_role_ref:
            print(
                f"force_cluster_role_ref for role {self.role_name} namespace {self.namespace.name}"
            )
            body["roleRef"]["kind"] = "ClusterRole"
            print(f"body: {body}")
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

    def if_role_exists(self, namespace_mapping: dict[str, bool]) -> bool:
        if self.role_name in COMMON_CLUSTER_ROLES:
            return False
        if not self.openshift_client:
            return False
        key = f"{self.namespace.cluster.name}/{self.namespace.name}/{self.role_name}"
        if key in namespace_mapping:
            return namespace_mapping[key]
        else:
            try:
                role_exist = bool(
                    self.openshift_client.get(
                        namespace=self.namespace.name,
                        kind="Role",
                        name=self.role_name,
                        allow_not_found=True,
                    )
                )
            except Exception as e:
                print(f"Error checking if role {self.role_name} exists: {e}")
                role_exist = False
        namespace_mapping[key] = role_exist
        return role_exist

    def get_oc_resources(self, namespace_mapping: dict[str, bool]) -> list[OCResource]:
        force_cluster_role_ref = False
        if self.role_kind == "Role":
            force_cluster_role_ref = not self.if_role_exists(namespace_mapping)
        user_oc_resources = [
            self.construct_user_oc_resource(username, force_cluster_role_ref)
            for username in self.username_list
        ]
        sa_oc_resources = [
            self.construct_sa_oc_resource(
                sa.sa_namespace_name, sa.sa_name, force_cluster_role_ref
            )
            for sa in self.openshift_service_accounts
        ]
        return user_oc_resources + sa_oc_resources

    def construct_sa_oc_resource(
        self, sa_namespace_name: str, sa_name: str, force_cluster_role_ref: bool
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
        if force_cluster_role_ref:
            body["roleRef"]["kind"] = "ClusterRole"
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
    oc_map: ob.ClusterMap | None,
    enforced_user_keys: list[str] | None = None,
) -> list[dict[str, str]]:
    roles: list[RoleV1] = expiration.filter(get_app_interface_roles())
    users_desired_state = []
    namespace_mapping: dict[str, bool] = {}
    for role in roles:
        rolebindings: list[RoleBindingSpec] = RoleBindingSpec.create_rb_specs_from_role(
            role, oc_map, enforced_user_keys
        )
        for rolebinding in rolebindings:
            print("******************* USERS   *****************************")
            print(f"rolebinding: {rolebinding.username_list}")
            print("******************* USERS   *****************************")
            users_desired_state.extend(rolebinding.get_users_desired_state())
            if ri is None:
                continue
            for oc_resource in rolebinding.get_oc_resources(namespace_mapping):
                with contextlib.suppress(ResourceKeyExistsError):
                    ri.add_desired(
                        rolebinding.cluster.name,
                        rolebinding.namespace.name,
                        "RoleBinding.rbac.authorization.k8s.io",
                        oc_resource.resource_name,
                        oc_resource.resource,
                        privileged=oc_resource.privileged,
                    )
    # print("************************************************")
    # print(f"namespace_mapping: {namespace_mapping}")
    # print("************************************************")
    print(f"users_desired_state: {users_desired_state}")
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
    fetch_desired_state(ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
