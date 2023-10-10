from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from unittest.mock import create_autospec

from reconcile.saas_auto_promotions_manager.integration import SaasAutoPromotionsManager
from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.saas_auto_promotions_manager.utils.saas_files_inventory import (
    SaasFilesInventory,
)
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS
from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.promotion_state import (
    PromotionData,
    PromotionState,
)


def test_integration_test(
    saas_files_builder: Callable[[Iterable[Mapping]], list[SaasFile]],
    vcs_builder: Callable[..., VCS],
    promotion_state_builder: Callable[..., PromotionState],
):
    """
    Have all the parts glued together and have one full run.
    This is too complex to setup and maintain for multiple
    test cases. However, it is a good single test to see if
    all components are wired properly.

    These saas files and states should result in a single
    merge request being opened.
    """
    saas_files = saas_files_builder(
        [
            {
                "path": "/saas1.yml",
                "name": "saas_1",
                "resourceTemplates": [
                    {
                        "name": "template_1",
                        "url": "repo1/url",
                        "targets": [
                            {
                                "ref": "main",
                                "namespace": {"path": "/namespace1.yml"},
                                "promotion": {
                                    "publish": ["channel-1"],
                                },
                            },
                            {
                                "ref": "main",
                                "namespace": {"path": "/namespace2.yml"},
                                "promotion": {
                                    "publish": ["channel-2"],
                                },
                            },
                        ],
                    }
                ],
            },
            {
                "path": "/saas2.yml",
                "name": "saas_2",
                "resourceTemplates": [
                    {
                        "name": "template_2",
                        "url": "repo1/url",
                        "targets": [
                            {
                                "ref": "current_sha",
                                "namespace": {"path": "/namespace3.yml"},
                                "promotion": {
                                    "subscribe": ["channel-1", "channel-2"],
                                    "auto": True,
                                },
                            }
                        ],
                    }
                ],
            },
        ]
    )
    vcs = vcs_builder()
    deployment_state = promotion_state_builder(
        [
            PromotionData(
                success=True,
                target_config_hash="new_hash",
                saas_file="saas_1",
            ),
            PromotionData(
                success=True,
                target_config_hash="new_hash",
                saas_file="saas_1",
            ),
        ]
    )
    renderer = create_autospec(spec=Renderer)
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    manager = SaasAutoPromotionsManager(
        deployment_state=deployment_state,
        saas_file_inventory=SaasFilesInventory(saas_files=saas_files),
        vcs=vcs,
        merge_request_manager=merge_request_manager,
        thread_pool_size=1,
        dry_run=False,
    )
    manager.reconcile()

    # Only one MR should be opened
    # TODO: assert MR data
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    vcs.open_app_interface_merge_request.assert_called_once()  # type: ignore[attr-defined]
