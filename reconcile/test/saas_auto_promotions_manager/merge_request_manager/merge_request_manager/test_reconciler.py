from collections.abc import Sequence
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.batcher import (
    Addition,
    Batcher,
    Deletion,
    Diff,
    Promotion,
    Reason,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.open_merge_requests import (
    OpenBatcherMergeRequest,
)


def _aggregate_hashes(items: Sequence[Addition | Deletion]) -> set[str]:
    hashes: set[str] = set()
    for item in items:
        if isinstance(item, Addition):
            hashes.update(item.content_hashes)
        else:
            hashes.update(item.mr.content_hashes)
    return hashes


def _aggregate_channels(items: Sequence[Addition | Deletion]) -> set[str]:
    channels: set[str] = set()
    for item in items:
        if isinstance(item, Addition):
            channels.update(item.channels)
        else:
            channels.update(item.mr.channels)
    return channels


@pytest.mark.parametrize(
    "desired_promotions, open_mrs, expected_diff",
    [
        # No open MRs. Aggregate desired promotions into single batched Promotion
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                ),
                Promotion(
                    channels={"chan2", "chan3"},
                    content_hashes={"hash2", "hash3"},
                ),
            ],
            [],
            Diff(
                deletions=[],
                additions=[
                    Addition(
                        channels={"chan1", "chan2", "chan3"},
                        content_hashes={"hash1", "hash2", "hash3"},
                        batchable=True,
                    ),
                ],
            ),
        ),
        # No desired promotions. We expect that every MR gets closed,
        # no matter its current state.
        (
            [],
            [
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=True,
                    is_batchable=True,
                ),
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan3"},
                    content_hashes={"hash3"},
                    failed_mr_check=False,
                    is_batchable=True,
                ),
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan4"},
                    content_hashes={"hash4"},
                    failed_mr_check=False,
                    is_batchable=False,
                ),
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan5"},
                    content_hashes={"hash5"},
                    failed_mr_check=True,
                    is_batchable=False,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenBatcherMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=True,
                            is_batchable=True,
                        ),
                        reason=Reason.MISSING_UNBATCHING,
                    ),
                    Deletion(
                        mr=OpenBatcherMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan3"},
                            content_hashes={"hash3"},
                            failed_mr_check=False,
                            is_batchable=True,
                        ),
                        reason=Reason.OUTDATED_CONTENT,
                    ),
                    Deletion(
                        mr=OpenBatcherMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan4"},
                            content_hashes={"hash4"},
                            failed_mr_check=False,
                            is_batchable=False,
                        ),
                        reason=Reason.OUTDATED_CONTENT,
                    ),
                    Deletion(
                        mr=OpenBatcherMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan5"},
                            content_hashes={"hash5"},
                            failed_mr_check=True,
                            is_batchable=False,
                        ),
                        reason=Reason.OUTDATED_CONTENT,
                    ),
                ],
                additions=[],
            ),
        ),
        # We have a single failed, but still marked as batchable MR.
        # The hashes in the failed MR are still desired state.
        # We expect this MR to be closed. Further, a new MR should be
        # opened that is marked as unbatchable. Each hash should have
        # its own separated MR.
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                ),
            ],
            [
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=True,
                    is_batchable=True,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenBatcherMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=True,
                            is_batchable=True,
                        ),
                        reason=Reason.MISSING_UNBATCHING,
                    )
                ],
                additions=[
                    Addition(
                        channels={"chan1"},
                        content_hashes={"hash1"},
                        batchable=False,
                    ),
                    Addition(
                        channels={"chan2"},
                        content_hashes={"hash2"},
                        batchable=False,
                    ),
                ],
            ),
        ),
        # We have an open valid batched MR. All desired promotions
        # are already addressed by that MR -> there is nothing to do.
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                ),
            ],
            [
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=False,
                    is_batchable=True,
                ),
            ],
            Diff(
                deletions=[],
                additions=[],
            ),
        ),
        # We have an open valid batched MR. However, there is a promotion
        # that is not addressed by the open MR.
        # We expect that the MR gets closed and a new
        # batched MR gets created which addresses all desired promotions.
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                ),
                Promotion(
                    channels={"chan3", "chan4"},
                    content_hashes={"hash3", "hash4"},
                ),
            ],
            [
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=False,
                    is_batchable=True,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenBatcherMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=False,
                            is_batchable=True,
                        ),
                        reason=Reason.NEW_BATCH,
                    )
                ],
                additions=[
                    Addition(
                        content_hashes={"hash1", "hash2", "hash3", "hash4"},
                        channels={"chan1", "chan2", "chan3", "chan4"},
                        batchable=True,
                    )
                ],
            ),
        ),
        # We want to promote 12 content hashes.
        # We surpass the current batch limit of 5.
        # We expect a total of 3 batch MRs to be created.
        # The existing open batch MR should be closed.
        (
            [
                Promotion(
                    channels={"chan1", "chan2", "chan3"},
                    content_hashes={"hash1", "hash2", "hash3"},
                ),
                Promotion(
                    channels={"chan4", "chan5", "chan6"},
                    content_hashes={"hash4", "hash5", "hash6"},
                ),
                Promotion(
                    channels={"chan7", "chan8", "chan9"},
                    content_hashes={"hash7", "hash8", "hash9"},
                ),
                Promotion(
                    channels={"chan10", "chan11", "chan12"},
                    content_hashes={"hash10", "hash11", "hash12"},
                ),
                Promotion(
                    channels={"chan13", "chan14"},
                    content_hashes={"hash13", "hash14"},
                ),
            ],
            [
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=False,
                    is_batchable=True,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenBatcherMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=False,
                            is_batchable=True,
                        ),
                        reason=Reason.NEW_BATCH,
                    )
                ],
                additions=[
                    Addition(
                        # Note, that we expect more than 5 hashes here. The reason is that the
                        # aggregated promotions consist of 3 hashes, i.e., 3+3 = 6
                        # This is expected and fine.
                        content_hashes={
                            "hash1",
                            "hash2",
                            "hash3",
                            "hash4",
                            "hash5",
                            "hash6",
                        },
                        channels={"chan1", "chan2", "chan3", "chan4", "chan5", "chan6"},
                        batchable=True,
                    ),
                    Addition(
                        content_hashes={
                            "hash7",
                            "hash8",
                            "hash9",
                            "hash10",
                            "hash11",
                            "hash12",
                        },
                        channels={
                            "chan7",
                            "chan8",
                            "chan9",
                            "chan10",
                            "chan11",
                            "chan12",
                        },
                        batchable=True,
                    ),
                    Addition(
                        content_hashes={"hash13", "hash14"},
                        channels={"chan13", "chan14"},
                        batchable=True,
                    ),
                ],
            ),
        ),
        # We have an unbatchable open MR.
        # We do not want any change on the existing unbatchable MR,
        # but at the same time expect a new MR to be opened for the new promotion.
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                ),
            ],
            [
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    failed_mr_check=False,
                    is_batchable=False,
                ),
            ],
            Diff(
                deletions=[],
                additions=[
                    Addition(
                        content_hashes={
                            "hash2",
                        },
                        channels={"chan2"},
                        batchable=True,
                    ),
                ],
            ),
        ),
        # We have multiple unbatchable open MRs.
        # We do not want any change on the existing unbatchable MRs,
        # but at the same time expect a new MR to be opened for the new promotions.
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                ),
                Promotion(
                    channels={"chan3"},
                    content_hashes={"hash3"},
                ),
                Promotion(
                    channels={"chan4"},
                    content_hashes={"hash4"},
                ),
            ],
            [
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    failed_mr_check=False,
                    is_batchable=False,
                ),
                OpenBatcherMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    failed_mr_check=False,
                    is_batchable=False,
                ),
            ],
            Diff(
                deletions=[],
                additions=[
                    Addition(
                        content_hashes={
                            "hash3",
                            "hash4",
                        },
                        channels={"chan3", "chan4"},
                        batchable=True,
                    ),
                ],
            ),
        ),
    ],
)
def test_reconcile(
    desired_promotions: list[Promotion],
    open_mrs: list[OpenBatcherMergeRequest],
    expected_diff: Diff,
) -> None:
    reconciler = Batcher()
    diff = reconciler.reconcile(
        desired_promotions=desired_promotions, open_mrs=open_mrs, batch_limit=5
    )

    # We do not care about the order. As the batcher is working on sets, this
    # is not deterministic
    assert len(diff.additions) == len(expected_diff.additions)
    assert _aggregate_hashes(diff.additions) == _aggregate_hashes(
        expected_diff.additions
    )
    assert _aggregate_channels(diff.additions) == _aggregate_channels(
        expected_diff.additions
    )

    # Deletions are actually processed in a deterministic way.
    assert len(diff.deletions) == len(expected_diff.deletions)
    for i in range(len(diff.deletions)):
        assert diff.deletions[i].mr.channels == expected_diff.deletions[i].mr.channels
        assert (
            diff.deletions[i].mr.content_hashes
            == expected_diff.deletions[i].mr.content_hashes
        )
        assert (
            diff.deletions[i].mr.failed_mr_check
            == expected_diff.deletions[i].mr.failed_mr_check
        )
        assert (
            diff.deletions[i].mr.is_batchable
            == expected_diff.deletions[i].mr.is_batchable
        )
        assert diff.deletions[i].reason == expected_diff.deletions[i].reason
