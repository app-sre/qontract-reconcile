from collections.abc import (
    Callable,
    Iterable,
)
from unittest.mock import call, create_autospec

from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    Renderer,
)
from reconcile.utils.vcs import VCS


def test_unbatch_multiple_valid(
    mr_parser_builder: Callable[[Iterable], MRParser],
    renderer: Renderer,
) -> None:
    # We have 2 MRs that failed MR check, but are marked as batchable
    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels="multiple,aggregated,channels",
            content_hashes="a,b,c",
            is_batchable=True,
            failed_mr_check=True,
        ),
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels="chan",
            content_hashes="d",
            is_batchable=True,
            failed_mr_check=True,
        ),
    ]
    mr_parser = mr_parser_builder(open_mrs)

    vcs = create_autospec(spec=VCS)
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        mr_parser=mr_parser,
        renderer=renderer,
    )
    expected_close_mr_calls = [
        call(
            mr.raw,
            "Closing this MR because it failed MR check and isn't marked un-batchable yet.",
        )
        for mr in open_mrs
    ]
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_has_calls(expected_close_mr_calls, any_order=True)
    assert vcs.close_app_interface_mr.call_count == 2
    assert merge_request_manager._unbatchable_hashes == set(["a", "b", "c", "d"])
    assert len(merge_request_manager._open_mrs) == 0


def test_unbatch_multiple_invalid(
    mr_parser_builder: Callable[[Iterable], MRParser],
    renderer: Renderer,
) -> None:
    open_mrs = [
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels="multiple,aggregated,channels",
            content_hashes="a,b,c",
            is_batchable=False,
            failed_mr_check=False,
        ),
        OpenMergeRequest(
            raw=create_autospec(spec=ProjectMergeRequest),
            channels="chan",
            content_hashes="d",
            is_batchable=True,
            failed_mr_check=False,
        ),
    ]
    mr_parser = mr_parser_builder(open_mrs)

    vcs = create_autospec(spec=VCS)
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        mr_parser=mr_parser,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_not_called()
    assert merge_request_manager._unbatchable_hashes == set()
    assert len(merge_request_manager._open_mrs) == 2
