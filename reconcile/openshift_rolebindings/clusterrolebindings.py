"""OpenShift ClusterRoleBindings integration.

Manages cluster-scoped ClusterRoleBindings across OpenShift clusters.
"""

import contextlib
import sys
from collections.abc import Callable

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.openshift_rolebindings.base import OpenShiftBindingsBase
from reconcile.utils import expiration, gql
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.openshift_resource import ResourceInventory, ResourceKeyExistsError
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-clusterrolebindings"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)




class ClusterRoleBindingsIntegration(OpenShiftBindingsBase):
    """Manages ClusterRoleBindings across OpenShift clusters."""

    NAMESPACE_CLUSTER_SCOPE = "cluster"

    @property
    def integration_name(self) -> str:
        return QONTRACT_INTEGRATION

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    @property
    def resource_kind(self) -> str:
        return "ClusterRoleBinding"

    def get_resources_to_reconcile(self) -> list[dict]:
        """Return clusters that have managed cluster roles."""
        return [
            cluster_info
            for cluster_info in queries.get_clusters()
            if cluster_info.get("managedClusterRoles")
            and cluster_info.get("automationToken")
        ]

    def fetch_current_state(
        self,
        items: list[dict],
        thread_pool_size: int,
        internal: bool | None,
        use_jump_host: bool,
    ) -> tuple[ResourceInventory, ob.ClusterMap]:
        """Fetch current ClusterRoleBindings state from clusters."""
        return ob.fetch_current_state(
            clusters=items,
            thread_pool_size=thread_pool_size,
            integration=self.integration_name,
            integration_version=self.integration_version,
            override_managed_types=[self.managed_type],
            internal=internal,
            use_jump_host=use_jump_host,
        )

@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    defer: Callable | None = None,
) -> None:
    """Run the ClusterRoleBindings integration.

    Args:
        dry_run: If True, don't make actual changes.
        thread_pool_size: Number of threads for parallel operations.
        internal: Filter for internal clusters.
        use_jump_host: Whether to use jump host for connections.
        defer: Deferred cleanup function.
    """
    integration = ClusterRoleBindingsIntegration()
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

