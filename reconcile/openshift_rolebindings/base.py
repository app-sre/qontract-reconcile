from reconcile.utils.runtime.integration import QontractReconcileIntegration


class OpenshiftRoleBindingsBase(QontractReconcileIntegration):
    def __init__(self, name: str, version: str):
        super().__init__(name, version)