from __future__ import annotations

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
