"""OpenShift RoleBindings integration.

Manages namespace-scoped RoleBindings within OpenShift namespaces.
"""

import sys
from collections.abc import Callable

import reconcile.openshift_base as ob
from reconcile.gql_definitions.common.app_interface_roles import NamespaceV1, RoleV1
from reconcile.gql_definitions.common.namespaces import NamespaceV1 as CommonNamespaceV1
from reconcile.openshift_rolebindings.base import OpenShiftBindingsBase
from reconcile.openshift_rolebindings.models import OCResource, RoleBindingSpec
from reconcile.typed_queries.app_interface_roles import get_app_interface_roles
from reconcile.typed_queries.namespaces import get_namespaces
from reconcile.utils import expiration
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard

QONTRACT_INTEGRATION = "openshift-rolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)


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

    def fetch_current_state(
        self,
        items: list[dict],
        thread_pool_size: int,
        internal: bool | None,
        use_jump_host: bool,
    ) -> tuple[ResourceInventory, ob.ClusterMap]:
        """Fetch current RoleBindings state from namespaces."""
        return ob.fetch_current_state(
            namespaces=items,
            thread_pool_size=thread_pool_size,
            integration=self.integration_name,
            integration_version=self.integration_version,
            override_managed_types=[self.managed_type],
            internal=internal,
            use_jump_host=use_jump_host,
        )

    def fetch_desired_state(
        self,
        ri: ResourceInventory | None,
        oc_map: ob.ClusterMap,
    ) -> list[dict[str, str]]:
        """Fetch desired RoleBindings state from app-interface roles.

        Args:
            ri: ResourceInventory to populate with desired state.
            oc_map: Map of OpenShift cluster connections.

        Returns:
            List of user desired state dictionaries.
        """
        allowed_clusters = set(oc_map.clusters())
        if not allowed_clusters:
            return []

        roles: list[RoleV1] = expiration.filter(get_app_interface_roles())
        users_desired_state: list[dict[str, str]] = []

        for role in roles:
            rolebindings = RoleBindingSpec.create_rb_specs_from_role(
                role,
                self.enforced_user_keys,
                self.support_role_ref,
                namespace_validator=is_valid_namespace,
            )
            rolebindings = [
                rb for rb in rolebindings if rb.cluster.name in allowed_clusters
            ]

            for rolebinding in rolebindings:
                users_desired_state.extend(rolebinding.get_users_desired_state())
                if ri is None:
                    continue
                for oc_resource in self._get_oc_resources(rolebinding):
                    if not ri.get_desired(
                        rolebinding.cluster.name,
                        rolebinding.namespace.name,
                        self.managed_type,
                        oc_resource.resource_name,
                    ):
                        ri.add_desired_resource(
                            cluster=rolebinding.cluster.name,
                            namespace=rolebinding.namespace.name,
                            resource=oc_resource.resource,
                            privileged=oc_resource.privileged,
                        )
        return users_desired_state

    def _get_oc_resources(self, rolebinding: RoleBindingSpec) -> list[OCResource]:
        """Generate OpenShift resources for a role binding specification.

        Args:
            rolebinding: The role binding specification.

        Returns:
            List of OCResource objects for users and service accounts.
        """
        user_resources = [
            self.construct_user_oc_resource(
                rolebinding.role_name,
                username,
                rolebinding.role_kind,
                rolebinding.privileged,
            )
            for username in rolebinding.usernames
        ]
        sa_resources = [
            self.construct_sa_oc_resource(
                rolebinding.role_name,
                sa.sa_namespace_name,
                sa.sa_name,
                rolebinding.role_kind,
                rolebinding.privileged,
            )
            for sa in rolebinding.openshift_service_accounts
        ]
        return user_resources + sa_resources


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    support_role_ref: bool = False,
    defer: Callable | None = None,
) -> None:
    """Run the RoleBindings integration.

    Args:
        dry_run: If True, don't make actual changes.
        thread_pool_size: Number of threads for parallel operations.
        internal: Filter for internal clusters.
        use_jump_host: Whether to use jump host for connections.
        support_role_ref: Whether to support Role references.
        defer: Deferred cleanup function.
    """
    integration = RoleBindingsIntegration(support_role_ref=support_role_ref)
    ri, oc_map = integration.reconcile(
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
    )
    if defer:
        defer(oc_map.cleanup)  # type: ignore[attr-defined]

    if ri.has_error_registered():
        sys.exit(1)

