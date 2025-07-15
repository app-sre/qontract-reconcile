from unittest.mock import create_autospec

from reconcile.saas_auto_promotions_manager.dependencies import Dependencies
from reconcile.saas_auto_promotions_manager.integration import (
    SaasAutoPromotionsManager,
    SaasAutoPromotionsManagerParams,
)
from reconcile.saas_auto_promotions_manager.utils.saas_files_inventory import (
    SaasFilesInventory,
)
from reconcile.utils.promotion_state import (
    PromotionState,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.state import State
from reconcile.utils.vcs import VCS


def test_sapm_reconcile_empty_states_no_change(secret_reader: SecretReaderBase) -> None:
    vcs = create_autospec(spec=VCS)
    dependencies = Dependencies(
        secret_reader=secret_reader,
        deployment_state=create_autospec(spec=PromotionState),
        vcs=vcs,
        saas_file_inventory=SaasFilesInventory(
            saas_files=[], thread_pool_size=1, secret_reader=secret_reader
        ),
        saas_deploy_state=create_autospec(spec=PromotionState),
        sapm_state=create_autospec(spec=State),
    )

    integration = SaasAutoPromotionsManager(
        params=SaasAutoPromotionsManagerParams(
            thread_pool_size=1,
            env_name=None,
            app_name=None,
        ),
        dependencies=dependencies,
    )

    integration.reconcile(
        thread_pool_size=1,
        dry_run=False,
    )

    vcs.close_app_interface_mr.assert_not_called()
    vcs.open_app_interface_merge_request.assert_not_called()
