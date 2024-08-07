from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from reconcile.saas_auto_promotions_manager.merge_request_manager.open_merge_requests import (
    OpenBatcherMergeRequest,
)


class Reason(Enum):
    MISSING_UNBATCHING = "Closing this MR because it failed MR check and isn't marked as un-batchable yet."
    OUTDATED_CONTENT = "Closing this MR because it has out-dated content."
    NEW_BATCH = "Closing this MR in favor of a new batch MR."


@dataclass(order=True)
class Promotion:
    content_hashes: set[str]
    channels: set[str]


@dataclass
class Deletion:
    mr: OpenBatcherMergeRequest
    reason: Reason


@dataclass
class Addition:
    content_hashes: set[str]
    channels: set[str]
    batchable: bool


@dataclass
class Diff:
    deletions: list[Deletion]
    additions: list[Addition]


class Batcher:
    """
    The batcher calculates a Diff. I.e., which MRs need to be opened (Addition)
    and which MRs need to be closed (Deletion). The batcher has no external
    dependencies and does not interact with VCS. The batcher expects to be
    given the desired state (which promotions do we want) and the current state
    (the currently open MRs) in order to calculate the Diff.
    """

    def __init__(self) -> None:
        self._desired_promotions: Iterable[Promotion] = []
        self._open_mrs: Iterable[OpenBatcherMergeRequest] = []

    def _unbatch(self, diff: Diff) -> None:
        """
        We optimistically batch MRs together that didnt run through MR check yet.
        Vast majority of auto-promotion MRs are succeeding checks, so we can stay optimistic.
        In the rare case of an MR failing the check, we want to unbatch it.
        I.e., we open a dedicated MR for each channel in the batched MR, mark the new MRs as non-batchable
        and close the old batched MR. By doing so, we ensure that unrelated MRs are not blocking each other.
        Unbatched MRs are marked and will never be batched again.
        """
        open_mrs_after_unbatching: list[OpenBatcherMergeRequest] = []
        unbatchable_hashes: set[str] = set()
        falsely_marked_batchable_hashes: set[str] = set()
        for mr in self._open_mrs:
            if not mr.is_batchable:
                unbatchable_hashes.update(mr.content_hashes)
                open_mrs_after_unbatching.append(mr)
            elif mr.failed_mr_check:
                falsely_marked_batchable_hashes.update(mr.content_hashes)
                diff.deletions.append(
                    Deletion(
                        mr=mr,
                        reason=Reason.MISSING_UNBATCHING,
                    )
                )
            else:
                open_mrs_after_unbatching.append(mr)
        self._open_mrs = open_mrs_after_unbatching

        desired_promotions_after_unbatching: list[Promotion] = []
        for promotion in self._desired_promotions:
            if promotion.content_hashes.issubset(unbatchable_hashes):
                desired_promotions_after_unbatching.append(promotion)
                continue
            elif promotion.content_hashes.issubset(falsely_marked_batchable_hashes):
                diff.additions.append(
                    Addition(
                        content_hashes=promotion.content_hashes,
                        channels=promotion.channels,
                        batchable=False,
                    )
                )
                continue
            else:
                desired_promotions_after_unbatching.append(promotion)
        self._desired_promotions = desired_promotions_after_unbatching

    def _remove_outdated(self, diff: Diff) -> None:
        """
        We want to be sure that the open MRs are still addressing desired content.
        We close MRs that are not addressing any content hash in a desired promotion.
        """
        all_desired_content_hashes: set[str] = set()
        for promotion in self._desired_promotions:
            all_desired_content_hashes.update(promotion.content_hashes)

        open_mrs_after_deletion: list[OpenBatcherMergeRequest] = []
        for mr in self._open_mrs:
            if mr.content_hashes.issubset(all_desired_content_hashes):
                open_mrs_after_deletion.append(mr)
                continue
            diff.deletions.append(
                Deletion(
                    mr=mr,
                    reason=Reason.OUTDATED_CONTENT,
                )
            )
        self._open_mrs = open_mrs_after_deletion

    def _batch_remaining_mrs(self, diff: Diff, batch_limit: int) -> None:
        """
        Remaining desired promotions should be batched together
        if they are not addressed yet by a valid open MR.

        We do not want to let MR batches grow infinitely,
        as constant change of a batch might starve MRs that
        are already part of the batch.
        In order for MRs to not grow infinitely, we apply a
        BATCH_LIMIT per MR, i.e., a maximum number of hashes
        that can be batched together.
        """
        submitted_content_hashes: set[str] = set()
        for open_mr in self._open_mrs:
            submitted_content_hashes.update(open_mr.content_hashes)

        unsubmitted_promotions = [
            prom
            for prom in self._desired_promotions
            if not prom.content_hashes.issubset(submitted_content_hashes)
        ]

        if not unsubmitted_promotions:
            return

        batch_with_capacity: OpenBatcherMergeRequest | None = None
        for mr in self._open_mrs:
            if mr.is_batchable and len(mr.content_hashes) < batch_limit:
                batch_with_capacity = mr
                # Note, there should always only be maximum one batch with capacity available
                break

        if batch_with_capacity:
            # We disassemble the batch to its promotions
            # can be added to new batch(es)
            unsubmitted_promotions.append(
                Promotion(
                    content_hashes=batch_with_capacity.content_hashes,
                    channels=batch_with_capacity.channels,
                )
            )
            # Lets close the current batch so remaining promotions can
            # be aggregated in new batch(es)
            diff.deletions.append(
                Deletion(
                    mr=batch_with_capacity,
                    reason=Reason.NEW_BATCH,
                )
            )

        batched_mr = Addition(
            content_hashes=set(),
            channels=set(),
            batchable=True,
        )

        for promotion in unsubmitted_promotions:
            batched_mr.content_hashes.update(promotion.content_hashes)
            batched_mr.channels.update(promotion.channels)
            if len(batched_mr.content_hashes) >= batch_limit:
                # Note, we might also be above the batch limit, but thats ok.
                # We only ensure that we create a new batch now and dont grow further.
                diff.additions.append(batched_mr)
                batched_mr = Addition(
                    content_hashes=set(),
                    channels=set(),
                    batchable=True,
                )
        if batched_mr.content_hashes:
            diff.additions.append(batched_mr)

    def reconcile(
        self,
        desired_promotions: Iterable[Promotion],
        open_mrs: Iterable[OpenBatcherMergeRequest],
        batch_limit: int,
    ) -> Diff:
        self._open_mrs = open_mrs
        self._desired_promotions = desired_promotions
        diff = Diff(
            deletions=[],
            additions=[],
        )
        self._unbatch(diff=diff)
        self._remove_outdated(diff=diff)
        self._batch_remaining_mrs(diff=diff, batch_limit=batch_limit)
        return diff
