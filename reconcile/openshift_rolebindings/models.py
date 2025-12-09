"""Shared data models for OpenShift role binding integrations."""

from dataclasses import dataclass
from typing import Any, Self

from pydantic import BaseModel

import reconcile.openshift_base as ob
from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    BotV1,
    ClusterV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.utils.openshift_resource import OpenshiftResource as OR


class OCResource(BaseModel, arbitrary_types_allowed=True):
    """Represents an OpenShift resource with metadata."""

    resource: OR
    resource_name: str
    privileged: bool = False


@dataclass
class ServiceAccountSpec:
    """Service account specification with namespace and name."""

    sa_namespace_name: str
    sa_name: str

    @classmethod
    def from_bots(cls, bots: list[BotV1] | None) -> list[Self]:
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
    cluster: ClusterV1
    usernames: set[str]
    openshift_service_accounts: list[ServiceAccountSpec]

    def get_users_desired_state(self) -> list[dict[str, str]]:
        """Return list of cluster/user mappings for desired state."""
        return [
            {"cluster": self.cluster.name, "user": username}
            for username in self.usernames
        ]

    @staticmethod
    def get_usernames_from_users(
        users: list[UserV1] | None, user_keys: list[str] | None
    ) -> set[str]:
        """Extract usernames from user objects using specified keys."""
        return {
            name
            for user in users or []
            for user_key in user_keys or []
            if (name := getattr(user, user_key, None))
        }


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
        bots: list[BotV1] | None = None,
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
        namespace_validator: Any = None,
    ) -> list[Self]:
        """Create list of RoleBindingSpec from a role configuration."""
        rolebinding_spec_list = [
            role_binding_spec
            for access in role.access or []
            if (
                access.namespace
                and (namespace_validator is None or namespace_validator(access.namespace))
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

    pass  # No namespace needed for cluster-scoped bindings

