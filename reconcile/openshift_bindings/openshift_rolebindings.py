"""OpenShift RoleBindings integration.

Manages namespace-scoped RoleBindings within OpenShift namespaces.
"""

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

import reconcile.openshift_base as ob
from reconcile.openshift_bindings.constants import (
    OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME,
)
from reconcile.openshift_bindings.models import RoleBindingSpec
from reconcile.openshift_bindings.utils import (
    is_valid_namespace,
)
from reconcile.typed_queries.app_interface_roles import get_app_interface_roles
from reconcile.typed_queries.namespaces import get_namespaces
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
    from reconcile.gql_definitions.common.app_interface_roles import RoleV1

QONTRACT_INTEGRATION_VERSION = make_semver(0, 3, 0)
QONTRACT_INTEGRATION_MANAGED_TYPE = "RoleBinding.rbac.authorization.k8s.io"


class OpenShiftRoleBindingsIntegrationParams(PydanticRunParams):
    support_role_ref: bool = False
    enforced_user_keys: list[str] | None = None
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE
    internal: bool | None = None
    use_jump_host: bool = True


class OpenShiftRoleBindingsIntegration(
    QontractReconcileIntegration[OpenShiftRoleBindingsIntegrationParams],
):
    """Manages RoleBindings within OpenShift namespaces."""

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        ri, oc_map = self.fetch_current_state()
        if defer:
            defer(oc_map.cleanup)
        self.fetch_desired_state(
            ri,
            support_role_ref=self.params.support_role_ref,
            enforced_user_keys=self.params.enforced_user_keys,
            allowed_clusters=set(oc_map.clusters()),
        )
        ob.publish_metrics(ri, self.name)
        ob.realize_data(dry_run, oc_map, ri, self.params.thread_pool_size)
        if ri.has_error_registered():
            sys.exit(1)

    @property
    def integration_version(self) -> str:
        return QONTRACT_INTEGRATION_VERSION

    @property
    def name(self) -> str:
        return OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME

    def fetch_current_state(self) -> tuple[ResourceInventory, OC_Map]:
        """Fetch current RoleBindings state from namespaces."""
        namespaces = [
            namespace.model_dump(by_alias=True, exclude={"openshift_resources"})
            for namespace in get_namespaces()
            if is_valid_namespace(namespace)
        ]
        return ob.fetch_current_state(
            namespaces=namespaces,
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
                for oc_resource in rolebinding.get_openshift_resources(
                    self.name,
                    self.integration_version,
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
