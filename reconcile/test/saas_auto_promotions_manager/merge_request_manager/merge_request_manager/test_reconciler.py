from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import ProjectMergeRequest

from reconcile.saas_auto_promotions_manager.merge_request_manager.mr_parser import (
    OpenMergeRequest,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.reconciler import (
    Addition,
    Deletion,
    Diff,
    Promotion,
    Reason,
    Reconciler,
)
from reconcile.saas_auto_promotions_manager.merge_request_manager.schedule import (
    Schedule,
)


def _aggregate_additions(
    items: Sequence[Addition],
) -> list[tuple[str, str, bool, Schedule, bool]]:
    result = [
        (
            "".join(sorted(list(item.content_hashes))),
            "".join(sorted(list(item.channels))),
            item.batchable,
            item.schedule,
            item.auto_merge,
        )
        for item in items
    ]
    return sorted(result)


@pytest.mark.parametrize(
    "desired_promotions, open_mrs, expected_diff",
    [
        # No open MRs. Aggregate desired promotions into single batched Promotion
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan2", "chan3"},
                    content_hashes={"hash2", "hash3"},
                    schedule=Schedule.now(),
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
                        schedule=Schedule.now(),
                        auto_merge=True,
                    ),
                ],
            ),
        ),
        # No desired promotions. We expect that every MR gets closed,
        # no matter its current state.
        (
            [],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=True,
                    is_batchable=True,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan3"},
                    content_hashes={"hash3"},
                    failed_mr_check=False,
                    is_batchable=True,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan4"},
                    content_hashes={"hash4"},
                    failed_mr_check=False,
                    is_batchable=False,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan5"},
                    content_hashes={"hash5"},
                    failed_mr_check=True,
                    is_batchable=False,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=True,
                            is_batchable=True,
                            schedule=Schedule.now(),
                            auto_merge=True,
                        ),
                        reason=Reason.MISSING_UNBATCHING,
                    ),
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan3"},
                            content_hashes={"hash3"},
                            failed_mr_check=False,
                            is_batchable=True,
                            schedule=Schedule.now(),
                            auto_merge=True,
                        ),
                        reason=Reason.OUTDATED_CONTENT,
                    ),
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan4"},
                            content_hashes={"hash4"},
                            failed_mr_check=False,
                            is_batchable=False,
                            schedule=Schedule.now(),
                            auto_merge=True,
                        ),
                        reason=Reason.OUTDATED_CONTENT,
                    ),
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan5"},
                            content_hashes={"hash5"},
                            failed_mr_check=True,
                            is_batchable=False,
                            schedule=Schedule.now(),
                            auto_merge=True,
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
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    schedule=Schedule.now(),
                ),
            ],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=True,
                    is_batchable=True,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=True,
                            is_batchable=True,
                            schedule=Schedule.now(),
                            auto_merge=True,
                        ),
                        reason=Reason.MISSING_UNBATCHING,
                    )
                ],
                additions=[
                    Addition(
                        channels={"chan1"},
                        content_hashes={"hash1"},
                        batchable=False,
                        schedule=Schedule.now(),
                        auto_merge=True,
                    ),
                    Addition(
                        channels={"chan2"},
                        content_hashes={"hash2"},
                        batchable=False,
                        schedule=Schedule.now(),
                        auto_merge=True,
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
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    schedule=Schedule.now(),
                ),
            ],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=False,
                    is_batchable=True,
                    schedule=Schedule.now(),
                    auto_merge=True,
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
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan3", "chan4"},
                    content_hashes={"hash3", "hash4"},
                    schedule=Schedule.now(),
                ),
            ],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=False,
                    is_batchable=True,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=False,
                            is_batchable=True,
                            schedule=Schedule.now(),
                            auto_merge=True,
                        ),
                        reason=Reason.NEW_BATCH,
                    )
                ],
                additions=[
                    Addition(
                        content_hashes={"hash1", "hash2", "hash3", "hash4"},
                        channels={"chan1", "chan2", "chan3", "chan4"},
                        batchable=True,
                        schedule=Schedule.now(),
                        auto_merge=True,
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
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan4", "chan5", "chan6"},
                    content_hashes={"hash4", "hash5", "hash6"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan7", "chan8", "chan9"},
                    content_hashes={"hash7", "hash8", "hash9"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan10", "chan11", "chan12"},
                    content_hashes={"hash10", "hash11", "hash12"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan13", "chan14"},
                    content_hashes={"hash13", "hash14"},
                    schedule=Schedule.now(),
                ),
            ],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1", "chan2"},
                    content_hashes={"hash1", "hash2"},
                    failed_mr_check=False,
                    is_batchable=True,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1", "chan2"},
                            content_hashes={"hash1", "hash2"},
                            failed_mr_check=False,
                            is_batchable=True,
                            schedule=Schedule.now(),
                            auto_merge=True,
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
                        schedule=Schedule.now(),
                        auto_merge=True,
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
                        schedule=Schedule.now(),
                        auto_merge=True,
                    ),
                    Addition(
                        content_hashes={"hash13", "hash14"},
                        channels={"chan13", "chan14"},
                        batchable=True,
                        schedule=Schedule.now(),
                        auto_merge=True,
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
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    schedule=Schedule.now(),
                ),
            ],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    failed_mr_check=False,
                    is_batchable=False,
                    schedule=Schedule.now(),
                    auto_merge=True,
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
                        schedule=Schedule.now(),
                        auto_merge=True,
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
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan3"},
                    content_hashes={"hash3"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan4"},
                    content_hashes={"hash4"},
                    schedule=Schedule.now(),
                ),
            ],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    failed_mr_check=False,
                    is_batchable=False,
                    schedule=Schedule.now(),
                    auto_merge=True,
                ),
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    failed_mr_check=False,
                    is_batchable=False,
                    schedule=Schedule.now(),
                    auto_merge=True,
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
                        schedule=Schedule.now(),
                        auto_merge=True,
                    ),
                ],
            ),
        ),
        # We have a promotion that is scheduled in the future.
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    schedule=Schedule(
                        data=(
                            datetime.now(tz=timezone.utc) + timedelta(hours=1)
                        ).isoformat()
                    ),
                ),
            ],
            [],
            Diff(
                deletions=[],
                additions=[
                    Addition(
                        content_hashes={
                            "hash1",
                        },
                        channels={"chan1"},
                        batchable=False,
                        schedule=Schedule(
                            data=(
                                datetime.now(tz=timezone.utc) + timedelta(hours=1)
                            ).isoformat()
                        ),
                        auto_merge=False,
                    ),
                ],
            ),
        ),
        # We have promotions that are scheduled in the future and now
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    schedule=Schedule(
                        data=(
                            datetime.now(tz=timezone.utc) + timedelta(hours=1)
                        ).isoformat()
                    ),
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    schedule=Schedule(
                        data=(
                            datetime.now(tz=timezone.utc) + timedelta(hours=1)
                        ).isoformat()
                    ),
                ),
                Promotion(
                    channels={"chan1", "chan2"},
                    content_hashes={"hash3", "hash4"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan3", "chan4"},
                    content_hashes={"hash5", "hash6"},
                    schedule=Schedule.now(),
                ),
            ],
            [],
            Diff(
                deletions=[],
                additions=[
                    Addition(
                        content_hashes={
                            "hash1",
                        },
                        channels={"chan1"},
                        batchable=False,
                        schedule=Schedule(
                            data=(
                                datetime.now(tz=timezone.utc) + timedelta(hours=1)
                            ).isoformat()
                        ),
                        auto_merge=False,
                    ),
                    Addition(
                        content_hashes={
                            "hash2",
                        },
                        channels={"chan2"},
                        batchable=False,
                        schedule=Schedule(
                            data=(
                                datetime.now(tz=timezone.utc) + timedelta(hours=1)
                            ).isoformat()
                        ),
                        auto_merge=False,
                    ),
                    Addition(
                        content_hashes={"hash3", "hash4", "hash5", "hash6"},
                        channels={"chan1", "chan2", "chan3", "chan4"},
                        batchable=True,
                        schedule=Schedule.now(),
                        auto_merge=True,
                    ),
                ],
            ),
        ),
        # We have an open MR that was scheduled for the future, but now reached its due date.
        (
            [
                Promotion(
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    schedule=Schedule.now(),
                ),
                Promotion(
                    channels={"chan2"},
                    content_hashes={"hash2"},
                    schedule=Schedule.now(),
                ),
            ],
            [
                OpenMergeRequest(
                    raw=create_autospec(spec=ProjectMergeRequest),
                    channels={"chan1"},
                    content_hashes={"hash1"},
                    failed_mr_check=False,
                    is_batchable=False,
                    schedule=Schedule.now(),
                    auto_merge=False,
                ),
            ],
            Diff(
                deletions=[
                    Deletion(
                        mr=OpenMergeRequest(
                            raw=create_autospec(spec=ProjectMergeRequest),
                            channels={"chan1"},
                            content_hashes={"hash1"},
                            failed_mr_check=False,
                            is_batchable=False,
                            schedule=Schedule.now(),
                            auto_merge=False,
                        ),
                        reason=Reason.REACHED_SCHEDULE,
                    )
                ],
                additions=[
                    Addition(
                        content_hashes={"hash1", "hash2"},
                        channels={"chan1", "chan2"},
                        batchable=True,
                        schedule=Schedule.now(),
                        auto_merge=True,
                    ),
                ],
            ),
        ),
    ],
)
def test_reconcile(
    desired_promotions: list[Promotion],
    open_mrs: list[OpenMergeRequest],
    expected_diff: Diff,
) -> None:
    reconciler = Reconciler()
    diff = reconciler.reconcile(
        desired_promotions=desired_promotions, open_mrs=open_mrs, batch_limit=5
    )

    # Additions are non-deterministic - we need a helper function to compare them
    additions = _aggregate_additions(diff.additions)
    expected_additions = _aggregate_additions(expected_diff.additions)
    for addition, expected_addition in zip(additions, expected_additions):
        assert addition[0] == expected_addition[0]
        assert addition[1] == expected_addition[1]
        assert addition[2] == expected_addition[2]
        assert addition[3].is_now() == expected_addition[3].is_now()
        # Lets give a safe 20 minute time window for CI to always pass
        assert addition[3].after <= expected_addition[3].after + timedelta(minutes=10)
        assert addition[3].after >= expected_addition[3].after - timedelta(minutes=10)
        assert addition[4] == expected_addition[4]

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
