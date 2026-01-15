"""OpenShift ClusterRoleBindings integration.

Manages cluster-scoped ClusterRoleBindings across OpenShift clusters.
"""

from typing import TYPE_CHECKING

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.openshift_bindings.base import OpenShiftBindingsBase
from reconcile.openshift_bindings.constants import (
    CLUSTER_ROLE_BINDING_RESOURCE_KIND,
    OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME,
)
from reconcile.openshift_bindings.models import ClusterRoleBindingSpec
from reconcile.typed_queries.app_interface_clusterroles import (
    get_app_interface_clusterroles,
)
from reconcile.utils import expiration
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from reconcile.gql_definitions.common.app_interface_clusterrole import RoleV1

QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_INTEGRATION_MANAGED_TYPE = "ClusterRoleBinding.rbac.authorization.k8s.io"
NAMESPACE_CLUSTER_SCOPE = "cluster"


class ClusterRoleBindingsIntegration(OpenShiftBindingsBase):
    """Manages ClusterRoleBindings across OpenShift clusters."""

    def __init__(
        self,
        thread_pool_size: int,
        internal: bool | None,
        use_jump_host: bool,
    ) -> None:
        """Initialize the ClusterRoleBindings integration.

        Args:
            thread_pool_size: Number of threads for parallel operations.
            internal: Filter for internal clusters.
            use_jump_host: Whether to use jump host for connections.
        """
        super().__init__(thread_pool_size, internal, use_jump_host)

    @property
    def integration_name(self) -> str:
        return OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    @property
    def resource_kind(self) -> str:
        return CLUSTER_ROLE_BINDING_RESOURCE_KIND

    def fetch_current_state(self) -> tuple[ResourceInventory, OC_Map]:
        clusters = [
            cluster_info
            for cluster_info in queries.get_clusters()
            if cluster_info.get("managedClusterRoles")
            and cluster_info.get("automationToken")
        ]
        return ob.fetch_current_state(
            clusters=clusters,
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
    ) -> None:
        if allowed_clusters is not None and not allowed_clusters:
            return
        if ri is None:
            return
        cluster_roles: list[RoleV1] = expiration.filter(
            get_app_interface_clusterroles()
        )
        cluster_role_binding_specs = [
            cluster_role_binding_spec
            for cluster_role in cluster_roles
            for cluster_role_binding_spec in ClusterRoleBindingSpec.create_cluster_role_binding_specs(
                cluster_role
            )
        ]
        if allowed_clusters:
            cluster_role_binding_specs = [
                cluster_role_binding_spec
                for cluster_role_binding_spec in cluster_role_binding_specs
                if cluster_role_binding_spec.cluster.name in allowed_clusters
            ]
        for cluster_role_binding_spec in cluster_role_binding_specs:
            for oc_resource in self.get_openshift_resources(cluster_role_binding_spec):
                if not ri.get_desired(
                    cluster_role_binding_spec.cluster.name,
                    NAMESPACE_CLUSTER_SCOPE,
                    QONTRACT_INTEGRATION_MANAGED_TYPE,
                    oc_resource.resource_name,
                ):
                    ri.add_desired(
                        cluster=cluster_role_binding_spec.cluster.name,
                        namespace=NAMESPACE_CLUSTER_SCOPE,
                        resource_type=QONTRACT_INTEGRATION_MANAGED_TYPE,
                        name=oc_resource.resource_name,
                        value=oc_resource.resource,
                    )
