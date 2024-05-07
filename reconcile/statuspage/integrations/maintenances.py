import logging
import sys

from reconcile.statuspage.atlassian import AtlassianStatusPageProvider
from reconcile.statuspage.integration import get_binding_state, get_status_pages
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "status-page-maintenances"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class StatusPageMaintenancesIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool = False) -> None:
        binding_state = get_binding_state(self.name, self.secret_reader)
        pages = get_status_pages()

        error = False
        for p in pages:
            try:
                page_provider = AtlassianStatusPageProvider.init_from_page(
                    page=p,
                    token=self.secret_reader.read_secret(p.credentials),
                    component_binding_state=binding_state,
                )
                maintenances = page_provider._api.list_maintenances()
                print(maintenances)
            except Exception:
                logging.exception(f"failed to reconcile statuspage {p.name}")
                error = True

        if error:
            sys.exit(1)
