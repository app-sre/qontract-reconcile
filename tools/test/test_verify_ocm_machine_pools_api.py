"""Tests for the E2E verification tool.

Regression tests for the plan-parity error comparison (two errors for
different pools must normalize to different identities) and for the
mutation gate (a pre-flight dry run showing unowned actions must never
reach a live call).
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from tools.e2e.verify_ocm_machine_pools_api import (
    MutationGateRefusedError,
    _gated_reconcile,
    _normalize_error,
)


def test_update_errors_for_different_pools_are_distinct() -> None:
    """Two instance_type rejections on the same cluster but different pools
    must not collapse into one identity."""
    a = (
        "can not update instance_type for existing pool on cluster my-cluster, "
        'CURRENT: {"id":"worker","instance_type":"m5.xlarge"}, '
        'DESIRED: {"id":"worker","instance_type":"m5.2xlarge"}'
    )
    b = (
        "can not update instance_type for existing pool on cluster my-cluster, "
        'CURRENT: {"id":"extra","instance_type":"m5.xlarge"}, '
        'DESIRED: {"id":"extra","instance_type":"m5.2xlarge"}'
    )
    assert _normalize_error(a) == ("update instance_type", "my-cluster", "worker")
    assert _normalize_error(b) == ("update instance_type", "my-cluster", "extra")
    assert _normalize_error(a) != _normalize_error(b)


def test_delete_guard_error_extracts_pool() -> None:
    """The delete-guard wording names the pool directly (no JSON)."""
    error = "can not delete machine pool worker for cluster my-cluster"
    assert _normalize_error(error) == (
        "delete protected pool",
        "my-cluster",
        "worker",
    )


def test_delete_all_error_has_no_pool() -> None:
    """The delete-all guard is cluster-scoped; the pool slot is empty."""
    error = "can not delete all machine pools for cluster my-cluster"
    assert _normalize_error(error) == ("delete all pools", "my-cluster", "-")


def test_same_error_on_different_clusters_is_distinct() -> None:
    a = "can not update subnet for existing pool on cluster c1, CURRENT: {...}"
    b = "can not update subnet for existing pool on cluster c2, CURRENT: {...}"
    assert _normalize_error(a)[1] != _normalize_error(b)[1]


def test_duplicate_errors_are_counted_not_collapsed() -> None:
    """Multiset semantics: two identical delete-all errors on one side and
    one on the other must produce a non-empty difference in both directions
    of the summary - a plain set difference hides the duplicate."""
    a = [
        "can not delete all machine pools for cluster c1",
        "can not delete all machine pools for cluster c1",
    ]
    b = ["can not delete all machine pools for cluster c1"]
    counter_a = Counter(_normalize_error(e) for e in a)
    counter_b = Counter(_normalize_error(e) for e in b)
    only_a = counter_a - counter_b
    only_b = counter_b - counter_a
    assert only_a  # the duplicate is visible
    assert not only_b  # nothing on the other side


def test_gated_reconcile_refusal_aborts_and_never_goes_live() -> None:
    """When the pre-flight dry run shows actions on pools this run does not
    own, the live call must never execute and the refusal must raise so the
    mutation pass aborts."""
    harness = _RefusingHarness()
    try:
        _gated_reconcile(harness, [], {"my-pool"}, "test-step")
        raise AssertionError("expected MutationGateRefusedError")
    except MutationGateRefusedError:
        pass
    assert harness.live_calls == 0


@dataclass
class _FakeAction:
    cluster: str
    pool_id: str
    action_type: str


@dataclass
class _FakeResult:
    actions: list[_FakeAction] = field(default_factory=list)


@dataclass
class _RefusingHarness:
    """Duck-typed ServiceHarness whose dry run always targets an unowned pool."""

    live_calls: int = 0

    def reconcile(self, clusters: Any, dry_run: bool) -> _FakeResult:
        if not dry_run:
            self.live_calls += 1
        return _FakeResult([
            _FakeAction("c1", "someone-elses-pool", "delete_machine_pool")
        ])
