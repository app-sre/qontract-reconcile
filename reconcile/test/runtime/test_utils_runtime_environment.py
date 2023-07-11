import pytest

from reconcile.utils.runtime.environment import log_fmt


def test_log_fmt_no_args():
    fmt = log_fmt()
    assert "DRY-RUN" not in fmt


def test_log_fmt_both_args():
    with pytest.raises(ValueError) as excinfo:
        log_fmt(dry_run=True, dry_run_option="--dry-run")

    assert "Please set either dry_run or dry_run_option." in str(excinfo.value)


def test_log_fmt_dry_run_true():
    fmt = log_fmt(dry_run=True)
    assert "DRY-RUN" in fmt


def test_log_fmt_dry_run_false():
    fmt = log_fmt(dry_run=False)
    assert "DRY-RUN" not in fmt


def test_log_fmt_dry_run_option():
    fmt = log_fmt(dry_run_option="--dry-run")
    assert "DRY-RUN" in fmt


def test_log_fmt_no_dry_run_option():
    fmt = log_fmt(dry_run_option="--no-dry-run")
    assert "DRY-RUN" not in fmt


def test_log_fmt_bad_dry_run_option():
    with pytest.raises(ValueError) as excinfo:
        log_fmt(dry_run_option="--bad-option")

    assert 'Invalid dry_run_option "--bad-option".' in str(excinfo.value)
