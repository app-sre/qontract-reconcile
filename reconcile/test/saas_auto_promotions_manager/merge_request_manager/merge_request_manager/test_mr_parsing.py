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
from reconcile.utils.vcs import VCS

from .data_keys import (
    DESCRIPTION,
    HAS_CONFLICTS,
    LABELS,
    OPEN_MERGE_REQUESTS,
)


def test_labels_filter(
    vcs_builder: Callable[[Mapping], VCS], renderer: Renderer
) -> None:
    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                LABELS: ["OtherLabel"],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: some_hash
                """,
            },
            {
                LABELS: [SAPM_LABEL, "OtherLabel"],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: other-channel
                    {CONTENT_HASHES}: other_hash
                """,
            },
        ]
    })
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    assert len(merge_request_manager._open_raw_mrs) == 1


def test_valid_description(
    vcs_builder: Callable[[Mapping], VCS], renderer: Renderer
) -> None:
    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: some_hash
                    {IS_BATCHABLE}: True
                """,
            }
        ]
    })
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 1


def test_valid_batching(
    vcs_builder: Callable[[Mapping], VCS], renderer: Renderer
) -> None:
    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: some_hash
                    {IS_BATCHABLE}: False
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: other-channel
                    {CONTENT_HASHES}: other_hash
                    {IS_BATCHABLE}: True
                """,
            },
        ]
    })
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_not_called()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 2


def test_bad_mrs(vcs_builder: Callable[[Mapping], VCS], renderer: Renderer) -> None:
    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    missing-version: some_version
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: hash_1
                    {IS_BATCHABLE}: True
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {IS_BATCHABLE}: True
                    missing-content-hash-key: some_hash
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    missing-data-separator
                    {VERSION_REF}: {SAPM_VERSION}
                    {CONTENT_HASHES}: hash_3
                    {IS_BATCHABLE}: True
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    bad order
                    {VERSION_REF}: {SAPM_VERSION}
                    {PROMOTION_DATA_SEPARATOR}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: hash_4
                    {IS_BATCHABLE}: True
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
                    {CONTENT_HASHES}: hash_5
                    {IS_BATCHABLE}: True
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: outdated-version
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: hash_6
                    {IS_BATCHABLE}: True
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    bad_channel_ref: some-channel
                    {CONTENT_HASHES}: hash_7
                    {IS_BATCHABLE}: True
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: hash_8
                    missing-batchable-key
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: hash_9
                    {IS_BATCHABLE}: Something-non-bool
                """,
            },
        ]
    })
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_called()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 0


def test_remove_duplicates(
    vcs_builder: Callable[[Mapping], VCS], renderer: Renderer
) -> None:
    vcs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some_channel
                    {CONTENT_HASHES}: same_hash
                    {IS_BATCHABLE}: True
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Some other blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some_channel
                    {CONTENT_HASHES}: same_hash
                    {IS_BATCHABLE}: True
                """,
            },
        ]
    })
    merge_request_manager = MergeRequestManager(
        vcs=vcs,
        renderer=renderer,
    )
    merge_request_manager.housekeeping()
    vcs.close_app_interface_mr.assert_called_once()  # type: ignore[attr-defined]
    assert len(merge_request_manager._open_mrs) == 1
