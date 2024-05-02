from collections.abc import (
    Callable,
    Mapping,
)
from unittest.mock import call

from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.merge_request_manager_v2 import (
    SAPM_LABEL,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    MRParser,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.open_merge_requests import (
    MRKind,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.renderer import (
    CHANNELS_REF,
    CONTENT_HASHES,
    IS_BATCHABLE,
    MR_KIND_REF,
    PROMOTION_DATA_SEPARATOR,
    SAPM_VERSION,
    VERSION_REF,
)
from reconcile.utils.vcs import VCS

from .data_keys import (
    DESCRIPTION,
    HAS_CONFLICTS,
    LABELS,
    OPEN_MERGE_REQUESTS,
)


def test_valid_parsing(
    vcs_builder: Callable[[Mapping], tuple[VCS, list[ProjectMergeRequest]]],
) -> None:
    vcs, expectd_mrs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: channel0
                    {CONTENT_HASHES}: hash0
                    {IS_BATCHABLE}: True
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: channel1
                    {CONTENT_HASHES}: hash1
                    {IS_BATCHABLE}: False
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
                """,
            },
        ]
    })
    mr_parser = MRParser(
        vcs=vcs,
    )
    mr_parser.fetch_mrs(label=SAPM_LABEL)
    open_mrs = mr_parser._open_batcher_mrs
    assert len(open_mrs) == 2

    assert open_mrs[0].raw == expectd_mrs[0]
    assert open_mrs[0].channels == {"channel0"}
    assert open_mrs[0].content_hashes == {"hash0"}
    assert open_mrs[0].is_batchable

    assert open_mrs[1].raw == expectd_mrs[1]
    assert open_mrs[1].channels == {"channel1"}
    assert open_mrs[1].content_hashes == {"hash1"}
    assert not open_mrs[1].is_batchable


def test_labels_filter(
    vcs_builder: Callable[[Mapping], tuple[VCS, list[ProjectMergeRequest]]],
) -> None:
    vcs, expectd_mrs = vcs_builder({
        OPEN_MERGE_REQUESTS: [
            {
                LABELS: [SAPM_LABEL, "OtherLabel"],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: other-channel
                    {CONTENT_HASHES}: other_hash
                    {IS_BATCHABLE}: True
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
                """,
            },
            # This MR should get ignored
            {
                LABELS: ["OtherLabel"],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: some_hash
                    {IS_BATCHABLE}: True
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
                """,
            },
        ]
    })
    mr_parser = MRParser(
        vcs=vcs,
    )
    mr_parser.fetch_mrs(label=SAPM_LABEL)
    open_mrs = mr_parser.get_open_batcher_mrs()
    assert len(open_mrs) == 1
    assert open_mrs[0].raw == expectd_mrs[0]


def test_bad_mrs(
    vcs_builder: Callable[[Mapping], tuple[VCS, list[ProjectMergeRequest]]],
) -> None:
    vcs, expected_mrs = vcs_builder({
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
                """,
            },
            {
                LABELS: [SAPM_LABEL],
                DESCRIPTION: f"""
                    Blabla
                    {PROMOTION_DATA_SEPARATOR}
                    {VERSION_REF}: {SAPM_VERSION}
                    {CHANNELS_REF}: some-channel
                    {CONTENT_HASHES}: hash_10
                    {IS_BATCHABLE}: True
                    {MR_KIND_REF}: blub
                """,
            },
        ]
    })
    mr_parser = MRParser(
        vcs=vcs,
    )
    expected_calls = [
        call(
            expected_mrs[0],
            "Closing this MR because of bad sapm_version format.",
        ),
        call(
            expected_mrs[1],
            "Closing this MR because of bad content_hashes format.",
        ),
        call(
            expected_mrs[2],
            "Closing this MR because of bad data separator format.",
        ),
        call(
            expected_mrs[3],
            "Closing this MR because of bad sapm_version format.",
        ),
        call(
            expected_mrs[4],
            "Closing this MR because of a merge-conflict.",
        ),
        call(
            expected_mrs[5],
            "Closing this MR because it has an outdated SAPM version outdated-version.",
        ),
        call(
            expected_mrs[6],
            "Closing this MR because of bad channels format.",
        ),
        call(
            expected_mrs[7],
            "Closing this MR because of bad is_batchable format.",
        ),
        call(
            expected_mrs[8],
            "Closing this MR because of bad is_batchable format.",
        ),
        call(
            expected_mrs[9],
            "Closing this MR because of bad kind format.",
        ),
    ]

    mr_parser.fetch_mrs(label=SAPM_LABEL)
    open_mrs = mr_parser.get_open_batcher_mrs()
    assert len(open_mrs) == 0
    vcs.close_app_interface_mr.assert_has_calls(expected_calls, any_order=True)  # type: ignore[attr-defined]
    assert vcs.close_app_interface_mr.call_count == len(expected_calls)  # type: ignore[attr-defined]


def test_remove_duplicates(
    vcs_builder: Callable[[Mapping], tuple[VCS, list[ProjectMergeRequest]]],
) -> None:
    vcs, expected_mrs = vcs_builder({
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
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
                    {MR_KIND_REF}: {MRKind.BATCHER.value}
                """,
            },
        ]
    })
    mr_parser = MRParser(
        vcs=vcs,
    )
    mr_parser.fetch_mrs(label=SAPM_LABEL)
    open_mrs = mr_parser.get_open_batcher_mrs()
    vcs.close_app_interface_mr.assert_has_calls([  # type: ignore[attr-defined]
        call(
            expected_mrs[1],
            "Closing this MR because there is already another MR open with identical content.",
        )
    ])
    assert vcs.close_app_interface_mr.call_count == 1  # type: ignore[attr-defined]
    assert len(open_mrs) == 1
    assert open_mrs[0].raw == expected_mrs[0]
