from collections.abc import Callable
from typing import Literal

from reconcile.openshift_bindings.base import OpenShiftBindingsBase
from reconcile.openshift_bindings.constants import (
    OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME,
    OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME,
    IntegrationNameType,
)
from reconcile.openshift_bindings.openshift_clusterrolebindings import (
    ClusterRoleBindingsIntegration,
)
from reconcile.openshift_bindings.openshift_rolebindings import RoleBindingsIntegration
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)


class OpenShiftBindingsIntegrationParams(PydanticRunParams):
    support_role_ref: bool = False
    enforced_user_keys: list[str] | None = None
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE
    internal: bool | None = None
    use_jump_host: bool = True
    integration_name: IntegrationNameType


class OpenShiftBindingsIntegration(
    QontractReconcileIntegration[OpenShiftBindingsIntegrationParams]
):
    @property
    def name(self) -> str:
        return self.params.integration_name

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        integration = get_rolebindings_integration(
            self.params.integration_name,
            self.params.thread_pool_size,
            self.params.internal,
            self.params.use_jump_host,
        )
        ri, oc_map = integration.fetch_current_state()
        if defer:
            defer(oc_map.cleanup)
        integration.reconcile(
            dry_run=dry_run,
            ri=ri,
            oc_map=oc_map,
            support_role_ref=self.params.support_role_ref,
            enforced_user_keys=self.params.enforced_user_keys,
        )


def get_rolebindings_integration(
    integration_name: IntegrationNameType,
    thread_pool_size: int,
    internal: bool | None,
    use_jump_host: bool,
) -> OpenShiftBindingsBase:
    if integration_name == OPENSHIFT_ROLEBINDINGS_INTEGRATION_NAME:
        return RoleBindingsIntegration(
            thread_pool_size=thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
        )
    if integration_name == OPENSHIFT_CLUSTERROLEBINDINGS_INTEGRATION_NAME:
        return ClusterRoleBindingsIntegration(
            thread_pool_size=thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
        )
    raise ValueError(f"Invalid integration name: {integration_name}")
