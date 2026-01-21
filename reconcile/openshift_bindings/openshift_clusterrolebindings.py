"""OpenShift ClusterRoleBindings integration.

Manages cluster-scoped ClusterRoleBindings across OpenShift clusters.
"""

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

import reconcile.openshift_base as ob
from reconcile.openshift_bindings.constants import (
    OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME,
)
from reconcile.openshift_bindings.models import ClusterRoleBindingSpec
from reconcile.typed_queries.app_interface_clusterroles import (
    get_app_interface_clusterroles,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils import expiration
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from reconcile.gql_definitions.common.app_interface_clusterrole import RoleV1

QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)
QONTRACT_INTEGRATION_MANAGED_TYPE = "ClusterRoleBinding.rbac.authorization.k8s.io"
NAMESPACE_CLUSTER_SCOPE = "cluster"


class OpenShiftClusterRoleBindingsIntegrationParams(PydanticRunParams):
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE
    internal: bool | None = None
    use_jump_host: bool = True


class OpenShiftClusterRoleBindingsIntegration(
    QontractReconcileIntegration[OpenShiftClusterRoleBindingsIntegrationParams],
):
    """Manages ClusterRoleBindings across OpenShift clusters."""

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        ri, oc_map = self.fetch_current_state()
        if defer:
            defer(oc_map.cleanup)
        self.fetch_desired_state(
            ri,
            allowed_clusters=set(oc_map.clusters()),
        )
        ob.publish_metrics(ri, self.name)
        ob.realize_data(dry_run, oc_map, ri, self.params.thread_pool_size)
        if ri.has_error_registered():
            sys.exit(1)

    @property
    def name(self) -> str:
        return OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    def fetch_current_state(self) -> tuple[ResourceInventory, OC_Map]:
        clusters = [
            cluster.model_dump(by_alias=True)
            for cluster in get_clusters()
            if cluster.managed_cluster_roles and cluster.automation_token is not None
        ]
        return ob.fetch_current_state(
            clusters=clusters,
            thread_pool_size=self.params.thread_pool_size,
            integration=self.name,
            integration_version=self.integration_version,
            override_managed_types=[QONTRACT_INTEGRATION_MANAGED_TYPE],
            internal=self.params.internal,
            use_jump_host=self.params.use_jump_host,
        )

    def fetch_desired_state(
        self,
        ri: ResourceInventory | None,
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
            for oc_resource in cluster_role_binding_spec.get_openshift_resources(
                self.name,
                self.integration_version,
            ):
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
