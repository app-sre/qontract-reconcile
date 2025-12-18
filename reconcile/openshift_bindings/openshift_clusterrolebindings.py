"""OpenShift ClusterRoleBindings integration.

Manages cluster-scoped ClusterRoleBindings across OpenShift clusters.
"""

import sys

from reconcile.gql_definitions.common.app_interface_clusterrole import RoleV1
import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.openshift_bindings.base import OpenShiftBindingsBase
from reconcile.openshift_bindings.models import ClusterRoleBindingSpec
from reconcile.typed_queries.app_interface_clusterroles import get_app_interface_clusterroles
from reconcile.utils import expiration
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-clusterrolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_INTEGRATION_MANAGED_TYPE = "ClusterRoleBinding.rbac.authorization.k8s.io"
NAMESPACE_CLUSTER_SCOPE = "cluster"
RESOURCE_KIND = "ClusterRoleBinding"

class ClusterRoleBindingsIntegration(OpenShiftBindingsBase):
    """Manages ClusterRoleBindings across OpenShift clusters."""

    
    

    @property
    def integration_name(self) -> str:
        return QONTRACT_INTEGRATION

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    @property
    def resource_kind(self) -> str:
        return RESOURCE_KIND

    def reconcile(
        self,
        dry_run: bool,
        ri: ResourceInventory,
        oc_map: OC_Map,   
    ) -> None:
        self.fetch_desired_state(ri, oc_map)
        ob.publish_metrics(ri, self.integration_name)
        ob.realize_data(dry_run, oc_map, ri, self.thread_pool_size)
        if ri.has_error_registered():
            sys.exit(1)

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

    def fetch_desired_state(self, ri: ResourceInventory | None, support_role_ref: bool = False, enforced_user_keys: list[str] | None = None, allowed_clusters: set[str] | None = None) -> list[dict[str, str]]:
        
        if allowed_clusters is not None and not allowed_clusters:
            return []
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
        return []
    
    def reconcile(
        self,
        dry_run: bool,
        ri: ResourceInventory,
        oc_map: OC_Map,
        support_role_ref: bool = False,
        enforced_user_keys: list[str] | None = None,
    ) -> None:
        self.fetch_desired_state(ri, support_role_ref, enforced_user_keys, allowed_clusters=set(oc_map.clusters()))
        ob.publish_metrics(ri, self.integration_name)
        ob.realize_data(dry_run, oc_map, ri, self.thread_pool_size)
        if ri.has_error_registered():
            sys.exit(1)