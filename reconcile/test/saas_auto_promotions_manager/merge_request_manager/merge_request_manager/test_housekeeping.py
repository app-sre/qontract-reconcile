from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    CONTENT_HASH,
    NAMESPACE_REF,
    SAPM_LABEL,
    TARGET_FILE_PATH,
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    PROMOTION_DATA_SEPARATOR,
    Renderer,
)
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS

from .data_keys import (
    DESCRIPTION,
    HAS_CONFLICTS,
    LABELS,
    OPEN_MERGE_REQUESTS,
)


def test_labels_filter(vcs_builder: Callable[[Mapping], VCS], renderer: Renderer):
    vcs = vcs_builder(
        {
            OPEN_MERGE_REQUESTS: [
                {
                    LABELS: ["OtherLabel"],
                    DESCRIPTION: "Some desc",
                },
                {
                    LABELS: [SAPM_LABEL, "OtherLabel"],
                    DESCRIPTION: "Some desc",
                },
            ]
        }
    )
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.fetch_sapm_managed_open_merge_requests()
    assert len(merge_request_manager._open_raw_mrs) == 1


def test_valid_description(vcs_builder: Callable[[Mapping], VCS], renderer: Renderer):
    vcs = vcs_builder(
        {
            OPEN_MERGE_REQUESTS: [
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {NAMESPACE_REF}: some_ref
                    {TARGET_FILE_PATH}: some_target
                    {CONTENT_HASH}: some_hash
                """,
                }
            ]
        }
    )
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.fetch_sapm_managed_open_merge_requests()
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 1


def test_bad_mrs(vcs_builder: Callable[[Mapping], VCS], renderer: Renderer):
    vcs = vcs_builder(
        {
            OPEN_MERGE_REQUESTS: [
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    missing-namespace-key: some_ref
                    {TARGET_FILE_PATH}: some_target
                    {CONTENT_HASH}: some_hash
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {NAMESPACE_REF}: some_ref
                    missing-target-key: some_target
                    {CONTENT_HASH}: some_hash
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {NAMESPACE_REF}: some_ref
                    {TARGET_FILE_PATH}: some_target
                    missing-content-hash-key: some_hash
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    missing-data-separator
                    {NAMESPACE_REF}: some_ref
                    {TARGET_FILE_PATH}: some_target
                    {CONTENT_HASH}: some_hash
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    bad order
                    {NAMESPACE_REF}: some_ref
                    {PROMOTION_DATA_SEPARATOR}
                    {TARGET_FILE_PATH}: some_target
                    {CONTENT_HASH}: some_hash
                """,
                },
                {
                    # We have merge conflicts here
                    HAS_CONFLICTS: True,
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {NAMESPACE_REF}: some_ref
                    {TARGET_FILE_PATH}: some_target
                    {CONTENT_HASH}: some_hash
                """,
                },
            ]
        }
    )
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.fetch_sapm_managed_open_merge_requests()
    merge_request_manager.housekeeping()
    # TODO: assert_has_calls()
    vcs.close_app_interface_mr.assert_called()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 0
