import logging
import sys

from reconcile.statuspage.atlassian import AtlassianStatusPageProvider
from reconcile.statuspage.integration import get_binding_state, get_status_pages
from reconcile.statuspage.page import StatusPage
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "status-page-components"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class StatusPageComponentsIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def reconcile(
        self,
        dry_run: bool,
        desired_state: StatusPage,
        current_state: StatusPage,
        provider: AtlassianStatusPageProvider,
    ) -> None:
        """
        Reconcile the desired state with the current state of a status page.
        """
        #
        # D E L E T E
        #
        desired_component_names = {c.name for c in desired_state.components}
        current_component_names = {c.name for c in current_state.components}
        component_names_to_delete = current_component_names - desired_component_names
        for component_name in component_names_to_delete:
            logging.info(
                f"delete component {component_name} from page {desired_state.name}"
            )
            provider.delete_component(dry_run, component_name)

        #
        # C R E A T E   OR   U P D A T E
        #
        for desired in desired_state.components:
            provider.apply_component(dry_run, desired)

    def run(self, dry_run: bool = False) -> None:
        binding_state = get_binding_state(self.name, self.secret_reader)
        pages = get_status_pages()

        error = False
        for p in pages:
            try:
                desired_state = StatusPage.init_from_page(p)
                page_provider = AtlassianStatusPageProvider.init_from_page(
                    page=p,
                    token=self.secret_reader.read_secret(p.credentials),
                    component_binding_state=binding_state,
                )
                self.reconcile(
                    dry_run,
                    desired_state=desired_state,
                    current_state=page_provider.get_current_page(),
                    provider=page_provider,
                )
            except Exception:
                logging.exception(f"failed to reconcile statuspage {p.name}")
                error = True

        if error:
            sys.exit(1)
