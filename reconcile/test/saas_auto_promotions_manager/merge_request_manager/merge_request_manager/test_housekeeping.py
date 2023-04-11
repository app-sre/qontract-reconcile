from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASH,
    PROMOTION_DATA_SEPARATOR,
    SAPM_LABEL,
    SAPM_VERSION,
    VERSION_REF,
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
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
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
                    missing-version: some_version
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASH}: hash_1
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    missing-content-hash-key: some_hash
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    missing-data-separator
                    {VERSION_REF}: {SAPM_VERSION}
                    {CONTENT_HASH}: hash_3
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    bad order
                    {VERSION_REF}: {SAPM_VERSION}
                    {PROMOTION_DATA_SEPARATOR}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASH}: hash_4
                """,
                },
                {
                    # We have merge conflicts here
                    HAS_CONFLICTS: True,
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASH}: hash_5
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: outdated-version
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASH}: hash_6
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    bad_channel_ref: some-channel
                    {CONTENT_HASH}: hash_7
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
    vcs.close_app_interface_mr.assert_called()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 0


def test_remove_duplicates(vcs_builder: Callable[[Mapping], VCS], renderer: Renderer):
    vcs = vcs_builder(
        {
            OPEN_MERGE_REQUESTS: [
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some_channel
                    {CONTENT_HASH}: same_hash
                """,
                },
                {
                    LABELS: [SAPM_LABEL],
                    DESCRIPTION: f"""
                    Some other blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some_channel
                    {CONTENT_HASH}: same_hash
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
    vcs.close_app_interface_mr.assert_called_once()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 1
