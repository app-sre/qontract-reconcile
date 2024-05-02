from unittest.mock import create_autospec

from reconcile.saas_auto_promotions_manager.integration import SaasAutoPromotionsManager
from reconcile.saas_auto_promotions_manager.merge_request_manager.batcher import (
    Batcher,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager_v2 import (
    MergeRequestManagerV2,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.s3_exporter import S3Exporter
from reconcile.saas_auto_promotions_manager.utils.saas_files_inventory import (
    SaasFilesInventory,
)
from reconcile.utils.promotion_state import (
    PromotionState,
)
from reconcile.utils.vcs import VCS


def test_integration_test():
    """
    Have all the parts glued together and have one full run.
    This is too complex to setup and properly maintain.
    However, it is a good single test to see if
    all components are wired properly.
    """
    vcs = create_autospec(spec=VCS)
    merge_request_manager_v2 = MergeRequestManagerV2(
        vcs=vcs,
        reconciler=create_autospec(spec=Batcher),
        mr_parser=create_autospec(spec=MRParser),
        renderer=create_autospec(spec=Renderer),
    )
    manager = SaasAutoPromotionsManager(
        deployment_state=create_autospec(spec=PromotionState),
        s3_exporter=create_autospec(spec=S3Exporter),
        saas_file_inventory=SaasFilesInventory(saas_files=[]),
        vcs=vcs,
        merge_request_manager_v2=merge_request_manager_v2,
        thread_pool_size=1,
        dry_run=False,
    )
    manager.reconcile()

    vcs.close_app_interface_mr.assert_not_called()
    vcs.open_app_interface_merge_request.assert_not_called()
