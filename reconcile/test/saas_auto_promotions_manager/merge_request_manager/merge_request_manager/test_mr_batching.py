from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASHES,
    IS_BATCHABLE,
    PROMOTION_DATA_SEPARATOR,
    SAPM_LABEL,
    SAPM_VERSION,
    VERSION_REF,
    Renderer,
)
from reconcile.utils.vcs import VCS, MRCheckStatus

from .data_keys import (
    DESCRIPTION,
    LABELS,
    OPEN_MERGE_REQUESTS,
    PIPELINE_RESULTS,
)


def test_housekeeping_unbatch_multiple_valid(
    vcs_builder: Callable[[Mapping], VCS], renderer: Renderer
) -> None:
    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            # The MR consists of multiple other MRs and is marked batchable
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: multiple,aggregated,channels
                    {CONTENT_HASHES}: a,b,c
                    {IS_BATCHABLE}: True
                """,
            },
            # The MR consists of a single hash, but is marked batchable
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: chan
                    {CONTENT_HASHES}: d
                    {IS_BATCHABLE}: True
                """,
            },
        ],
        # All MR checks fail
        PIPELINE_RESULTS: [MRCheckStatus.FAILED, MRCheckStatus.FAILED],
    })
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    assert vcs.close_app_interface_mr.call_count == 2  # type: ignore[attr-defined]
    assert merge_request_manager._unbatchable_hashes == set(["a", "b", "c", "d"])
    assert len(merge_request_manager._open_mrs) == 0


def test_housekeeping_unbatch_multiple_invalid(
    vcs_builder: Callable[[Mapping], VCS], renderer: Renderer
) -> None:
    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                # Already marked as not batchable -> should be ignored
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: multiple,aggregated,channels
                    {CONTENT_HASHES}: a,b,c
                    {IS_BATCHABLE}: False
                """,
            },
            {
                # Batchable and pipeline succeeds
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: chan
                    {CONTENT_HASHES}: d
                    {IS_BATCHABLE}: True
                """,
            },
        ],
        PIPELINE_RESULTS: [MRCheckStatus.SUCCESS, MRCheckStatus.SUCCESS],
    })
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    assert merge_request_manager._unbatchable_hashes == set()
    assert len(merge_request_manager._open_mrs) == 2
