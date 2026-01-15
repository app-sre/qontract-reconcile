"""OpenShift RoleBindings integration.

Manages namespace-scoped RoleBindings within OpenShift namespaces.
"""

from typing import TYPE_CHECKING

import reconcile.openshift_base as ob
from reconcile.openshift_bindings.base import OpenShiftBindingsBase
from reconcile.openshift_bindings.constants import (
    OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME,
    ROLE_BINDING_RESOURCE_KIND,
)
from reconcile.openshift_bindings.models import RoleBindingSpec, is_valid_namespace
from reconcile.typed_queries.app_interface_roles import get_app_interface_roles
from reconcile.typed_queries.namespaces import get_namespaces
from reconcile.utils import expiration
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from reconcile.gql_definitions.common.app_interface_roles import RoleV1

QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)
QONTRACT_INTEGRATION_MANAGED_TYPE = "RoleBinding.rbac.authorization.k8s.io"


class RoleBindingsIntegration(OpenShiftBindingsBase):
    """Manages RoleBindings within OpenShift namespaces."""

    def __init__(
        self,
        thread_pool_size: int,
        internal: bool | None,
        use_jump_host: bool,
    ) -> None:
        """Initialize the RoleBindings integration.

        Args:
            thread_pool_size: Number of threads for parallel operations.
            internal: Filter for internal clusters.
            use_jump_host: Whether to use jump host for connections.
        """
        super().__init__(thread_pool_size, internal, use_jump_host)

    @property
    def integration_name(self) -> str:
        return OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    @property
    def resource_kind(self) -> str:
        return ROLE_BINDING_RESOURCE_KIND

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
    ) -> None:
        if allowed_clusters is not None and not allowed_clusters:
            return
        if ri is None:
            return
        roles: list[RoleV1] = expiration.filter(get_app_interface_roles())
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
                for oc_resource in self.get_openshift_resources(
                    rolebinding,
                    privileged=rolebinding.privileged,
                ):
                    if not ri.get_desired(
                        rolebinding.cluster.name,
                        rolebinding.namespace.name,
                        QONTRACT_INTEGRATION_MANAGED_TYPE,
                        oc_resource.resource_name,
                    ):
                        ri.add_desired(
                            cluster=rolebinding.cluster.name,
                            namespace=rolebinding.namespace.name,
                            resource_type=QONTRACT_INTEGRATION_MANAGED_TYPE,
                            name=oc_resource.resource_name,
                            value=oc_resource.resource,
                            privileged=oc_resource.privileged,
                        )
