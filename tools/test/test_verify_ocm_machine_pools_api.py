"""Tests for the E2E verification tool's error normalization.

Regression tests for the plan-parity error comparison: two errors for
different pools must normalize to different identities, even when the
guard category and cluster are identical.
"""

from tools.e2e.verify_ocm_machine_pools_api import _normalize_error


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
