from typing import Callable, Literal

from reconcile.openshift_bindings.openshift_clusterrolebindings import ClusterRoleBindingsIntegration
from reconcile.openshift_bindings.openshift_rolebindings import RoleBindingsIntegration
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.runtime.integration import PydanticRunParams, QontractReconcileIntegration



class OpenShiftBindingsIntegrationParams(PydanticRunParams):
    support_role_ref: bool = False
    enforced_user_keys: list[str] | None = None
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE
    internal: bool | None = None
    use_jump_host: bool = True
    integration_name: Literal["openshift-rolebindings", "openshift-clusterrolebindings"]
    

class OpenShiftBindingsIntegration(QontractReconcileIntegration[OpenShiftBindingsIntegrationParams]):
    @property
    def name(self) -> str:
        return self.params.integration_name
    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        integration = get_rolebindings_integration(self.params.integration_name)
        if defer:
            defer(integration.cleanup)
        integration.reconcile(
            dry_run=dry_run,
            thread_pool_size=self.params.thread_pool_size,
            internal=self.params.internal,
            use_jump_host=self.params.use_jump_host,
            support_role_ref=self.params.support_role_ref,
            enforced_user_keys=self.params.enforced_user_keys,
        )


def get_rolebindings_integration(integration_name: Literal["openshift-rolebindings", "openshift-clusterrolebindings"]) -> RoleBindingsIntegration | ClusterRoleBindingsIntegration:
    match integration_name:
        case "openshift-rolebindings":
            return RoleBindingsIntegration()
        case "openshift-clusterrolebindings":
            return ClusterRoleBindingsIntegration()   