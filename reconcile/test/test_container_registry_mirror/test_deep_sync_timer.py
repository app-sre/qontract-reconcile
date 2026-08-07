from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest

from reconcile.container_registry_mirror.deep_sync_timer import DeepSyncTimer

NOW = 1662124612.995397


class TestShouldRun:
    """DeepSyncTimer.should_run determines whether a slow manifest
    comparison should execute this cycle."""

    def test_no_control_file_triggers_sync(self) -> None:
        """First run (or volume wipe) should trigger deep sync because
        there is no record of a previous run."""
        timer = DeepSyncTimer(
            control_file_path="/nonexistent/path/timestamp",
            interval=86400,
        )
        assert timer.should_run is True

    @patch("time.time", return_value=NOW)
    def test_interval_elapsed_triggers_sync(self, _mock_time: object) -> None:
        """When enough time has passed since the last deep sync, the
        timer should trigger."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, encoding="locale"
        ) as fp:
            fp.write(str(NOW - 200.0))
            path = fp.name

        try:
            timer = DeepSyncTimer(control_file_path=path, interval=100)
            assert timer.should_run is True
        finally:
            os.unlink(path)

    @patch("time.time", return_value=NOW)
    def test_interval_not_elapsed_skips_sync(self, _mock_time: object) -> None:
        """When insufficient time has passed, the timer should not
        trigger."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, encoding="locale"
        ) as fp:
            fp.write(str(NOW - 50.0))
            path = fp.name

        try:
            timer = DeepSyncTimer(control_file_path=path, interval=100)
            assert timer.should_run is False
        finally:
            os.unlink(path)

    def test_result_is_cached(self) -> None:
        """The file should be read at most once per timer instance to
        avoid repeated I/O during the sync loop."""
        timer = DeepSyncTimer(
            control_file_path="/nonexistent/path/timestamp",
            interval=86400,
        )
        first = timer.should_run
        second = timer.should_run
        assert first is second is True


class TestCliOverride:
    """The compare_tags_override parameter bypasses the timer entirely,
    used for debugging or incident response."""

    def test_force_true_overrides_timer(self) -> None:
        """--compare-tags should force deep sync regardless of the
        control file state."""
        timer = DeepSyncTimer(
            control_file_path="/nonexistent/path/timestamp",
            interval=86400,
            compare_tags_override=True,
        )
        assert timer.should_run is True

    @patch("time.time", return_value=NOW)
    def test_force_false_overrides_timer(self, _mock_time: object) -> None:
        """--no-compare-tags should suppress deep sync even when the
        interval has elapsed."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, encoding="locale"
        ) as fp:
            fp.write(str(NOW - 200.0))
            path = fp.name

        try:
            timer = DeepSyncTimer(
                control_file_path=path,
                interval=100,
                compare_tags_override=False,
            )
            assert timer.should_run is False
        finally:
            os.unlink(path)


class TestRecord:
    """record() writes the current timestamp to the control file."""

    def test_writes_timestamp(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as fp:
            path = fp.name

        try:
            timer = DeepSyncTimer(control_file_path=path, interval=86400)
            timer.record()

            with open(path, encoding="locale") as f:
                value = float(f.read())
            assert value > 0
        finally:
            os.unlink(path)


class TestFromDir:
    """from_dir constructs a timer with the control file path resolved
    from a directory and a filename."""

    def test_uses_given_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            timer = DeepSyncTimer.from_dir(
                control_file_dir=tmp_dir,
                control_file_name="test.timestamp",
                interval=86400,
            )
            assert timer.control_file_path == os.path.join(tmp_dir, "test.timestamp")

    def test_uses_tempdir_when_no_dir_given(self) -> None:
        timer = DeepSyncTimer.from_dir(
            control_file_dir=None,
            control_file_name="test.timestamp",
            interval=86400,
        )
        assert timer.control_file_path == os.path.join(
            tempfile.gettempdir(), "test.timestamp"
        )

    def test_nonexistent_dir_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            DeepSyncTimer.from_dir(
                control_file_dir="/no-such-dir",
                control_file_name="test.timestamp",
                interval=86400,
            )
