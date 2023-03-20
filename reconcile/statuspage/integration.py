import logging
import sys
from collections.abc import Callable

from reconcile.gql_definitions.statuspage import statuspages
from reconcile.gql_definitions.statuspage.statuspages import StatusPageV1
from reconcile.statuspage.page import (
    StatusPage,
    StatusPageProvider,
    build_status_page,
    init_provider_for_page,
)
from reconcile.statuspage.state import S3ComponentBindingState
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import (
    State,
    init_state,
)

QONTRACT_INTEGRATION = "status-page-components"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def get_status_pages(query_func: Callable) -> list[StatusPageV1]:
    return statuspages.query(query_func).status_pages or []


def get_state(secret_reader: SecretReaderBase) -> State:
    return init_state(
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
    )


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
        provider: StatusPageProvider,
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
        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        with get_state(secret_reader) as state:
            binding_state = S3ComponentBindingState(state)
            pages = get_status_pages(query_func=gql.get_api().query)

            error = False
            for p in pages:
                try:
                    desired_state = build_status_page(p)
                    page_provider = init_provider_for_page(
                        page=p,
                        token=secret_reader.read_secret(p.credentials),
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
