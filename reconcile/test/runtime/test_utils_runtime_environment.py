import pytest

from reconcile.utils.runtime.environment import log_fmt


def test_log_fmt_no_args() -> None:
    fmt = log_fmt()
    assert "DRY-RUN" not in fmt


def test_log_fmt_both_args() -> None:
    with pytest.raises(ValueError) as excinfo:
        log_fmt(dry_run=True, dry_run_option="--dry-run")

    assert "Please set either dry_run or dry_run_option." in str(excinfo.value)


def test_log_fmt_dry_run_true() -> None:
    fmt = log_fmt(dry_run=True)
    assert "DRY-RUN" in fmt


def test_log_fmt_dry_run_false() -> None:
    fmt = log_fmt(dry_run=False)
    assert "DRY-RUN" not in fmt


def test_log_fmt_dry_run_option() -> None:
    fmt = log_fmt(dry_run_option="--dry-run")
    assert "DRY-RUN" in fmt


def test_log_fmt_no_dry_run_option() -> None:
    fmt = log_fmt(dry_run_option="--no-dry-run")
    assert "DRY-RUN" not in fmt


def test_log_fmt_bad_dry_run_option() -> None:
    with pytest.raises(ValueError) as excinfo:
        log_fmt(dry_run_option="--bad-option")

    assert 'Invalid dry_run_option "--bad-option".' in str(excinfo.value)
