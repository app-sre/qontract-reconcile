from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from reconcile.change_owners.change_types import ChangeTypePriority
from reconcile.utils.mr.labels import (
    APPROVED,
    AUTO_MERGE,
    AWAITING_APPROVAL,
    BLOCKED_BOT_ACCESS,
    CHANGES_REQUESTED,
    DO_NOT_MERGE_HOLD,
    DO_NOT_MERGE_PENDING_REVIEW,
    HOLD,
    LGTM,
    MERGE_ERROR,
    NEEDS_REBASE,
    PIPELINE_ERROR,
    REBASE_ERROR,
    SELF_SERVICEABLE,
    prioritized_approval_label,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from gitlab.v4.objects import ProjectMergeRequest

MERGE_LABELS_PRIORITY = [
    prioritized_approval_label(p.value) for p in ChangeTypePriority
] + [
    APPROVED,
    AUTO_MERGE,
    LGTM,
]
HOLD_LABELS = [
    AWAITING_APPROVAL,
    BLOCKED_BOT_ACCESS,
    CHANGES_REQUESTED,
    HOLD,
    DO_NOT_MERGE_HOLD,
    DO_NOT_MERGE_PENDING_REVIEW,
    NEEDS_REBASE,
]

ERROR_LABELS = frozenset({MERGE_ERROR, PIPELINE_ERROR, REBASE_ERROR})

TENANT_LABEL_PREFIX = "tenant-"


def is_good_to_merge(labels: Iterable[str]) -> bool:
    return any(m in MERGE_LABELS_PRIORITY for m in labels) and not any(
        b in HOLD_LABELS for b in labels
    )


def get_tenant_labels(mr: ProjectMergeRequest) -> set[str]:
    """Return the subset of MR labels that start with ``tenant-``.

    Tenant labels identify the namespace an MR touches and are used by
    the optimistic multi-merge (OMM) logic to determine overlap: two MRs
    sharing a tenant label cannot be merged concurrently.
    """
    return {label for label in mr.labels if label.startswith(TENANT_LABEL_PREFIX)}


def is_eligible_for_optimistic_merge(mr: ProjectMergeRequest) -> bool:
    """Return True if the MR carries at least one tenant label.

    Only MRs with tenant labels can participate in OMM groups because the
    non-overlap guarantee depends on label-based scope tracking.  MRs
    without tenant labels are conservatively serialised.
    """
    return bool(get_tenant_labels(mr))


def has_overlapping_labels(mr_labels: set[str], merged_labels: set[str]) -> bool:
    """Return True if any tenant label appears in both sets.

    Used during OMM group formation to ensure that a candidate MR does
    not touch any namespace that has already been merged or is pending
    in the current group.
    """
    return bool(mr_labels & merged_labels)


@dataclass(frozen=True)
class MrLabelStatus:
    """Semantic facts derived purely from an MR's current label set.

    This is a read-only interpretation layer: it answers "what do these
    labels mean" without re-deriving the same answer independently in
    every consumer (merge queue, review queue, OMM, gitlab-owners). It
    intentionally only looks at labels - no pipelines, comments, or label
    event history - so it stays free to compute and safe for any consumer
    to call regardless of how much else that consumer needs.
    """

    merge_priority: int | None
    is_held: bool
    has_error: bool
    is_self_serviceable: bool
    tenant_labels: frozenset[str]

    @property
    def is_good_to_merge(self) -> bool:
        return self.merge_priority is not None and not self.is_held


def compute_mr_label_status(labels: Iterable[str]) -> MrLabelStatus:
    label_set = frozenset(labels)
    merge_priorities = [
        MERGE_LABELS_PRIORITY.index(label)
        for label in MERGE_LABELS_PRIORITY
        if label in label_set
    ]
    return MrLabelStatus(
        merge_priority=min(merge_priorities) if merge_priorities else None,
        is_held=any(label in label_set for label in HOLD_LABELS),
        has_error=any(label in label_set for label in ERROR_LABELS),
        is_self_serviceable=SELF_SERVICEABLE in label_set,
        tenant_labels=frozenset(
            label for label in label_set if label.startswith(TENANT_LABEL_PREFIX)
        ),
    )
