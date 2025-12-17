"""OpenShift RoleBindings integration.

Manages namespace-scoped RoleBindings within OpenShift namespaces.
"""

import reconcile.openshift_base as ob
from reconcile.gql_definitions.common.app_interface_roles import NamespaceV1, RoleV1
from reconcile.gql_definitions.common.namespaces import NamespaceV1 as CommonNamespaceV1
from reconcile.openshift_bindings.base import OpenShiftBindingsBase
from reconcile.openshift_bindings.models import RoleBindingSpec
from reconcile.typed_queries.app_interface_roles import get_app_interface_roles
from reconcile.typed_queries.namespaces import get_namespaces
from reconcile.utils import expiration
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard

QONTRACT_INTEGRATION = "openshift-rolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)
QONTRACT_INTEGRATION_MANAGED_TYPE = "RoleBinding.rbac.authorization.k8s.io"


def is_valid_namespace(
    namespace: NamespaceV1 | CommonNamespaceV1,
) -> bool:
    """Check if namespace should be managed for role bindings.

    Args:
        namespace: The namespace to validate.

    Returns:
        True if the namespace should be managed.
    """
    return (
        bool(namespace.managed_roles)
        and is_in_shard(f"{namespace.cluster.name}/{namespace.name}")
        and not ob.is_namespace_deleted(namespace.model_dump(by_alias=True))
    )


class RoleBindingsIntegration(OpenShiftBindingsBase):
    """Manages RoleBindings within OpenShift namespaces."""

    def __init__(
        self,
        support_role_ref: bool = False,
        enforced_user_keys: list[str] | None = None,
    ) -> None:
        """Initialize the RoleBindings integration.

        Args:
            support_role_ref: Whether to support Role references (not just ClusterRole).
            enforced_user_keys: List of user keys to enforce for access.
        """
        self.support_role_ref = support_role_ref
        self.enforced_user_keys = enforced_user_keys

    @property
    def integration_name(self) -> str:
        return QONTRACT_INTEGRATION

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    @property
    def resource_kind(self) -> str:
        return "RoleBinding"

    def get_resources_to_reconcile(self) -> list[dict]:
        """Return namespaces that have managed roles."""
        return [
            namespace.model_dump(by_alias=True, exclude={"openshift_resources"})
            for namespace in get_namespaces()
            if is_valid_namespace(namespace)
        ]

    def fetch_current_state(self) -> tuple[ResourceInventory, OC_Map]:
        """Fetch current RoleBindings state from namespaces."""
        namespaces = [
            namespace.model_dump(by_alias=True, exclude={"openshift_resources"})
            for namespace in get_namespaces()
            if is_valid_namespace(namespace)
        ]
        return ob.fetch_current_state(
            namespaces=namespaces,
            thread_pool_size=self.thread_pool_size,
            integration=self.integration_name,
            integration_version=self.integration_version,
            override_managed_types=[QONTRACT_INTEGRATION_MANAGED_TYPE],
            internal=self.internal,
            use_jump_host=self.use_jump_host,
        )

    def fetch_desired_state(
        self,
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
            rolebindings: list[RoleBindingSpec] = (
                RoleBindingSpec.create_rb_specs_from_role(
                    role, enforced_user_keys, support_role_ref
                )
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
                for oc_resource in self.get_openshift_resources(
                    rolebinding, rolebinding.privileged
                ):
                    ri.add_desired_resource(
                        cluster=rolebinding.cluster.name,
                        namespace=rolebinding.namespace.name,
                        resource=oc_resource.resource,
                        privileged=oc_resource.privileged,
                    )
        return users_desired_state
