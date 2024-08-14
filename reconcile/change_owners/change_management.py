from reconcile.change_owners.bundle import (
    QontractServerDiff,
)
from reconcile.utils.runtime.integration import NoParams, QontractReconcileIntegration
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import init_state


class ChangeManagementIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration = "change-management"
        self.qontract_integration_version = make_semver(0, 1, 0)

    @property
    def name(self) -> str:
        return self.qontract_integration

    def run(self, dry_run: bool) -> None:
        state = init_state(
            integration=self.name,
        )
        state.state_path = "bundle-archive/diff"
        for item in state.ls():
            obj = state.get(item.lstrip("/"), None)
            if not obj:
                continue
            diff = QontractServerDiff(**obj)
            # do something with this diff
            print(diff)
