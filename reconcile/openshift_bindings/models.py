"""Shared data models for openshift-rolebindings and openshift-clusterrolebindings integrations."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Self

from pydantic import BaseModel

import reconcile.openshift_base as ob
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    BotV1 as ClusterBotV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    ClusterV1 as ClusterRoleClusterV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    RoleV1 as ClusterRoleV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    UserV1 as ClusterUserV1,
)
from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.gql_definitions.common.app_interface_roles import (
    BotV1 as RoleBotV1,
)
from reconcile.gql_definitions.common.app_interface_roles import (
    ClusterV1 as RoleClusterV1,
)
from reconcile.openshift_bindings.constants import (
    CLUSTER_ROLE_BINDING_RESOURCE_KIND,
    CLUSTER_ROLE_KIND,
    ROLE_BINDING_RESOURCE_KIND,
    ROLE_KIND,
)
from reconcile.openshift_bindings.utils import is_valid_namespace
from reconcile.utils.openshift_resource import OpenshiftResource as OR


class OCResource(BaseModel, arbitrary_types_allowed=True):
    """Represents an OpenShift resource with metadata."""

    resource: OR
    resource_name: str
    privileged: bool = False


@dataclass
class OCResourceData:
    body: dict[str, Any]
    name: str


@dataclass
class ServiceAccountSpec:
    """Service account specification with namespace and name."""

    sa_namespace_name: str
    sa_name: str

    @classmethod
    def from_bots(cls, bots: Sequence[RoleBotV1 | ClusterBotV1] | None) -> list[Self]:
        """Create ServiceAccountSpec list from bot configurations."""
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


class BindingSpec(BaseModel, validate_by_alias=True, arbitrary_types_allowed=True):
    """Base specification for role bindings (cluster or namespace scoped)."""

    role_name: str
    role_kind: str  # "Role" or "ClusterRole"
    cluster: RoleClusterV1 | ClusterRoleClusterV1
    resource_kind: str
    usernames: set[str]
    openshift_service_accounts: list[ServiceAccountSpec]

    @staticmethod
    def get_usernames_from_users(
        users: Sequence[UserV1 | ClusterUserV1] | None,
        user_keys: list[str] | None = None,
    ) -> set[str]:
        """Extract usernames from user objects using depending on the user keys."""
        return {
            name
            for user in users or []
            for user_key in user_keys or []
            if (name := getattr(user, user_key, None))
        }

    def get_oc_resources(self) -> list[OCResourceData]:
        user_oc_resources = [
            self.construct_user_oc_resource(username) for username in self.usernames
        ]
        sa_oc_resources = [
            self.construct_sa_oc_resource(sa.sa_namespace_name, sa.sa_name)
            for sa in self.openshift_service_accounts
        ]
        return user_oc_resources + sa_oc_resources

    def construct_user_oc_resource(self, username: str) -> OCResourceData:
        name = f"{self.role_name}-{username}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": self.resource_kind,
            "metadata": {"name": name},
            "roleRef": {"kind": self.role_kind, "name": self.role_name},
            "subjects": [{"kind": "User", "name": username}],
        }
        return OCResourceData(body=body, name=name)

    def construct_sa_oc_resource(
        self, sa_namespace_name: str, sa_name: str
    ) -> OCResourceData:
        name = f"{self.role_name}-{sa_namespace_name}-{sa_name}"
        body: dict[str, Any] = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": self.resource_kind,
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
        return OCResourceData(body=body, name=name)

    def get_openshift_resources(
        self,
        integration_name: str,
        integration_version: str,
        privileged: bool = False,
    ) -> list[OCResource]:
        oc_resources = [
            OCResource(
                resource=OR(
                    oc_resource_data.body,
                    integration_name,
                    integration_version,
                    error_details=oc_resource_data.name,
                ),
                resource_name=oc_resource_data.name,
                privileged=privileged,
            )
            for oc_resource_data in self.get_oc_resources()
        ]
        return oc_resources


class RoleBindingSpec(BindingSpec):
    """Namespace-scoped RoleBinding specification."""

    namespace: NamespaceV1
    privileged: bool = False

    @classmethod
    def create_role_binding_spec(
        cls,
        access: AccessV1,
        users: list[UserV1] | None = None,
        enforced_user_keys: list[str] | None = None,
        bots: list[RoleBotV1] | None = None,
        support_role_ref: bool = False,
    ) -> Self | None:
        """Create a RoleBindingSpec from access configuration."""
        if not access.namespace:
            return None
        if not (access.role or access.cluster_role):
            return None
        privileged = access.namespace.cluster_admin or False
        auth_dict = [
            auth.model_dump(by_alias=True) for auth in access.namespace.cluster.auth
        ]
        usernames = cls.get_usernames_from_users(
            users,
            ob.determine_user_keys_for_access(
                access.namespace.cluster.name,
                auth_dict,
                enforced_user_keys,
            ),
        )
        service_accounts = ServiceAccountSpec.from_bots(bots) if bots else []
        role_kind = ROLE_KIND if access.role and support_role_ref else CLUSTER_ROLE_KIND
        return cls(
            role_name=access.role or access.cluster_role,
            role_kind=role_kind,
            namespace=access.namespace,
            cluster=access.namespace.cluster,
            privileged=privileged,
            usernames=usernames,
            openshift_service_accounts=service_accounts,
            resource_kind=ROLE_BINDING_RESOURCE_KIND,
        )

    @classmethod
    def create_rb_specs_from_role(
        cls,
        role: RoleV1,
        enforced_user_keys: list[str] | None = None,
        support_role_ref: bool = False,
    ) -> list[Self]:
        """Create list of RoleBindingSpec from a role configuration."""
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


class ClusterRoleBindingSpec(BindingSpec):
    """Cluster-scoped ClusterRoleBinding specification."""

    @classmethod
    def create_cluster_role_binding_specs(
        cls, cluster_role: ClusterRoleV1
    ) -> list[Self]:
        cluster_role_binding_specs = [
            cls(
                cluster=access.cluster,
                usernames=BindingSpec.get_usernames_from_users(
                    users=cluster_role.users,
                    user_keys=cls.get_user_keys(access.cluster),
                ),
                openshift_service_accounts=ServiceAccountSpec.from_bots(
                    cluster_role.bots
                ),
                role_name=access.cluster_role,
                role_kind=CLUSTER_ROLE_KIND,
                resource_kind=CLUSTER_ROLE_BINDING_RESOURCE_KIND,
            )
            for access in cluster_role.access or []
            if access.cluster and access.cluster_role
        ]
        return cluster_role_binding_specs

    @classmethod
    def get_user_keys(cls, cluster: ClusterRoleClusterV1) -> list[str] | None:
        auth_dict = [auth.model_dump(by_alias=True) for auth in cluster.auth]
        user_keys = ob.determine_user_keys_for_access(cluster.name, auth_dict)
        return user_keys
