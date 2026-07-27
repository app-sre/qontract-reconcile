from __future__ import annotations

import os
import tempfile
import time


class DeepSyncTimer:
    """Controls when the engine runs expensive manifest comparisons.

    Routine sync runs only mirror tags that are missing at the
    destination (fast, tag-list-only). Periodically, a deep sync
    fetches and compares manifests to detect drift on mutable tags
    (e.g., "latest" pointing to a different digest upstream). This
    timer decides whether the current run should be a deep sync
    based on how much time has elapsed since the last one."""

    def __init__(
        self,
        control_file_path: str,
        interval: int,
        compare_tags_override: bool | None = None,
    ) -> None:
        self.control_file_path = control_file_path
        self.interval = interval
        # CLI --compare-tags / --no-compare-tags bypasses the timer.
        self._override = compare_tags_override
        # Computed lazily and cached so the file is read at most once.
        self._cached_result: bool | None = None

    @classmethod
    def from_dir(
        cls,
        control_file_dir: str | None,
        control_file_name: str,
        interval: int,
        compare_tags_override: bool | None = None,
    ) -> DeepSyncTimer:
        """Construct a timer with the control file path resolved from
        a directory and filename. A persistent directory (e.g., a
        mounted volume in Kubernetes) allows the timestamp to survive
        pod restarts."""
        if control_file_dir:
            if not os.path.isdir(control_file_dir):
                raise FileNotFoundError(
                    f"'{control_file_dir}' does not exist or it is not a directory"
                )
            path = os.path.join(control_file_dir, control_file_name)
        else:
            path = os.path.join(tempfile.gettempdir(), control_file_name)

        return cls(
            control_file_path=path,
            interval=interval,
            compare_tags_override=compare_tags_override,
        )

    @property
    def should_run(self) -> bool:
        """Whether the current run should include manifest comparisons."""
        if self._override is not None:
            return self._override

        if self._cached_result is None:
            self._cached_result = self._check_elapsed_time()
        return self._cached_result

    def record(self) -> None:
        """Write the current timestamp to the control file after a
        successful deep sync."""
        with open(self.control_file_path, "w", encoding="locale") as f:
            f.write(str(time.time()))

    def _check_elapsed_time(self) -> bool:
        try:
            with open(self.control_file_path, encoding="locale") as f:
                last_sync = float(f.read())
        except FileNotFoundError, ValueError:
            # First run, volume wipe, or corrupt/empty file from an
            # interrupted write (e.g., pod OOM-killed mid-record).
            return True

        next_sync = last_sync + self.interval
        return time.time() >= next_sync
