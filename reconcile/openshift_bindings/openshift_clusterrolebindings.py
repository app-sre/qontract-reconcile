"""OpenShift ClusterRoleBindings integration.

Manages cluster-scoped ClusterRoleBindings across OpenShift clusters.
"""

import sys

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.openshift_bindings.base import OpenShiftBindingsBase
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-clusterrolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_INTEGRATION_MANAGED_TYPE = "ClusterRoleBinding.rbac.authorization.k8s.io"


class ClusterRoleBindingsIntegration(OpenShiftBindingsBase):
    """Manages ClusterRoleBindings across OpenShift clusters."""

    NAMESPACE_CLUSTER_SCOPE = "cluster"
    RESOURCE_KIND = "ClusterRoleBinding"

    @property
    def integration_name(self) -> str:
        return QONTRACT_INTEGRATION

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    @property
    def resource_kind(self) -> str:
        return self.RESOURCE_KIND

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

    def fetch_desired_state(self, ri: ResourceInventory, oc_map: ob.ClusterMap) -> None:
        pass
