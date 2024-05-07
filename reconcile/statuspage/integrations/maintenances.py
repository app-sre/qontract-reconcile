import logging
import sys

from reconcile.statuspage.atlassian import AtlassianStatusPageProvider
from reconcile.statuspage.integration import get_binding_state, get_status_pages
from reconcile.statuspage.page import StatusMaintenance
from reconcile.utils.differ import diff_iterables
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "status-page-maintenances"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class StatusPageMaintenancesIntegration(QontractReconcileIntegration[NoParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def reconcile(
        self,
        dry_run: bool,
        desired_state: list[StatusMaintenance],
        current_state: list[StatusMaintenance],
        provider: AtlassianStatusPageProvider,
    ) -> None:
        diff = diff_iterables(
            current=current_state, desired=desired_state, key=lambda x: x.name
        )
        for a in diff.add.values():
            logging.info(f"Create StatusPage Maintenance: {a.name}")
            if not dry_run:
                provider.create_maintenance(a)
        for c in diff.change.values():
            raise NotImplementedError(
                f"Update StatusPage Maintenance is not supported at this time: {c.desired.name}"
            )
        for d in diff.delete.values():
            raise NotImplementedError(
                f"Delete StatusPage Maintenance is not supported at this time: {d.name}"
            )

    def run(self, dry_run: bool = False) -> None:
        binding_state = get_binding_state(self.name, self.secret_reader)
        pages = get_status_pages()

        error = False
        for p in pages:
            try:
                desired_state = [
                    StatusMaintenance.init_from_maintenance(m)
                    for m in p.maintenances or []
                ]
                page_provider = AtlassianStatusPageProvider.init_from_page(
                    page=p,
                    token=self.secret_reader.read_secret(p.credentials),
                    component_binding_state=binding_state,
                )
                self.reconcile(
                    dry_run=dry_run,
                    desired_state=desired_state,
                    current_state=page_provider.maintenances,
                    provider=page_provider,
                )
            except Exception:
                logging.exception(f"failed to reconcile statuspage {p.name}")
                error = True

        if error:
            sys.exit(1)
