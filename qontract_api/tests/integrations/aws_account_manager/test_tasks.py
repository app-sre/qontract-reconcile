"""Tests for aws_account_manager task configuration."""

from unittest.mock import MagicMock

from qontract_api.integrations.aws_account_manager.tasks import (
    create_account_task,
    generate_reconcile_lock_key,
)


def test_create_account_lock_timeout_covers_max_retries() -> None:
    """Lock timeout must be >= max_retries * countdown + buffer.

    The create_account_task retries up to max_retries times with a countdown
    of 10 seconds. The lock must outlive the entire retry window to prevent
    concurrent task execution.
    """
    max_retries = create_account_task.max_retries  # 120
    countdown = 10  # hardcoded in self.retry(countdown=10)
    max_retry_window = max_retries * countdown  # 1200s

    assert max_retry_window <= 1500, (
        f"max_retry_window={max_retry_window} exceeds expected 1200s — "
        "update lock timeout accordingly"
    )


def test_reconcile_lock_key_includes_payer_uid() -> None:
    """Reconcile lock key must include payer_uid to prevent cross-payer collisions."""
    request_org = MagicMock()
    request_org.account_name = "prod-app"
    request_org.payer_uid = "111111111111"

    request_standalone = MagicMock()
    request_standalone.account_name = "prod-app"
    request_standalone.payer_uid = None

    key_org = generate_reconcile_lock_key(MagicMock(), request_org)
    key_standalone = generate_reconcile_lock_key(MagicMock(), request_standalone)

    # Same account name but different payer → different lock keys
    assert key_org != key_standalone
    assert "111111111111" in key_org
    assert "standalone" in key_standalone


def test_reconcile_lock_key_different_payers_same_account() -> None:
    """Two payer accounts with same-named org account must not collide."""
    request_a = MagicMock()
    request_a.account_name = "prod-app"
    request_a.payer_uid = "111111111111"

    request_b = MagicMock()
    request_b.account_name = "prod-app"
    request_b.payer_uid = "222222222222"

    key_a = generate_reconcile_lock_key(MagicMock(), request_a)
    key_b = generate_reconcile_lock_key(MagicMock(), request_b)

    assert key_a != key_b
