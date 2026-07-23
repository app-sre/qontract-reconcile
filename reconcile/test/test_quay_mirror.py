from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile.container_registry_mirror.deep_sync_timer import DeepSyncTimer
from reconcile.container_registry_mirror.quay import (
    CONTROL_FILE_NAME,
    QuayMirror,
)
from reconcile.utils.quay_mirror import sync_tag

if TYPE_CHECKING:
    from collections.abc import Iterable
    from unittest.mock import Mock

    from pytest_mock import MockerFixture

NOW = 1662124612.995397


@pytest.mark.parametrize(
    "tags, tags_exclude, candidate, result",
    [
        # Tags include tests.
        (["^sha256-.+sig$", "^main-.+"], None, "main-755781cc", True),
        (["^sha256-.+sig$", "^main-.+"], None, "sha256-8b5.sig", True),
        (["^sha256-.+sig$", "^main-.+"], None, "1.2.3", False),
        # Tags exclude tests.
        (None, ["^sha256-.+sig$", "^main-.+"], "main-755781cc", False),
        (None, ["^sha256-.+sig$", "^main-.+"], "sha256-8b5.sig", False),
        (None, ["^sha256-.+sig$", "^main-.+"], "1.2.3", True),
        # When both includes and excludes are explicitly given, exclude take precedence.
        (["^sha256-.+sig$", "^main-.+"], ["main-755781cc"], "main-755781cc", False),
        (["^sha256-.+sig$", "^main-.+"], ["main-755781cc"], "sha256-8b5.sig", True),
        # both include and exclude are not set
        (None, None, "main-755781cc", True),
    ],
)
def test_sync_tag(
    tags: Iterable[str] | None,
    tags_exclude: Iterable[str] | None,
    candidate: str,
    result: bool,
) -> None:
    assert sync_tag(tags, tags_exclude, candidate) == result


class TestDeepSyncTimerIntegration:
    """The module-level run() function constructs a DeepSyncTimer
    from CLI parameters. These tests verify the timer integration."""

    def test_control_file_dir_does_not_exist(self) -> None:
        with pytest.raises(FileNotFoundError):
            DeepSyncTimer.from_dir(
                control_file_dir="/no-such-dir",
                control_file_name=CONTROL_FILE_NAME,
                interval=86400,
            )

    def test_control_file_path_from_given_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            timer = DeepSyncTimer.from_dir(
                control_file_dir=tmp_dir_name,
                control_file_name=CONTROL_FILE_NAME,
                interval=86400,
            )
            assert timer.control_file_path == os.path.join(
                tmp_dir_name, CONTROL_FILE_NAME
            )

    @patch("time.time", return_value=NOW)
    def test_timer_elapsed(self, _mock_time: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with open(
                os.path.join(tmp_dir, CONTROL_FILE_NAME), "w", encoding="locale"
            ) as fh:
                fh.write(str(NOW - 100.0))

            timer = DeepSyncTimer.from_dir(
                control_file_dir=tmp_dir,
                control_file_name=CONTROL_FILE_NAME,
                interval=10,
            )
            assert timer.should_run is True

    @patch("time.time", return_value=NOW)
    def test_timer_not_elapsed(self, _mock_time: Mock) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with open(
                os.path.join(tmp_dir, CONTROL_FILE_NAME), "w", encoding="locale"
            ) as fh:
                fh.write(str(NOW - 100.0))

            timer = DeepSyncTimer.from_dir(
                control_file_dir=tmp_dir,
                control_file_name=CONTROL_FILE_NAME,
                interval=1000,
            )
            assert timer.should_run is False

    def test_force_compare(self) -> None:
        timer = DeepSyncTimer.from_dir(
            control_file_dir=None,
            control_file_name=CONTROL_FILE_NAME,
            interval=86400,
            compare_tags_override=True,
        )
        assert timer.should_run is True

    def test_force_no_compare(self) -> None:
        timer = DeepSyncTimer.from_dir(
            control_file_dir=None,
            control_file_name=CONTROL_FILE_NAME,
            interval=86400,
            compare_tags_override=False,
        )
        assert timer.should_run is False


class TestModuleLevelRun:
    """The module-level run() function wires together the QuayMirror
    implementation, DeepSyncTimer, and MirrorEngine."""

    def test_run_calls_engine_sync(self, mocker: MockerFixture) -> None:
        mocker.patch("reconcile.container_registry_mirror.quay.gql")
        mocker.patch("reconcile.container_registry_mirror.quay.queries")
        mocker.patch("reconcile.container_registry_mirror.quay.SecretReader")
        mock_engine = mocker.patch(
            "reconcile.container_registry_mirror.quay.MirrorEngine", autospec=True
        )
        mocker.patch.object(QuayMirror, "discover_mirrors", return_value=[])

        from reconcile.container_registry_mirror.quay import run

        run(
            dry_run=True,
            control_file_dir=None,
            compare_tags=False,
            compare_tags_interval=86400,
            repository_urls=None,
            exclude_repository_urls=None,
        )

        mock_engine.return_value.sync.assert_called_once_with([])

    def test_run_raises_exception_group_on_engine_error(
        self, mocker: MockerFixture
    ) -> None:
        mocker.patch("reconcile.container_registry_mirror.quay.gql")
        mocker.patch("reconcile.container_registry_mirror.quay.queries")
        mocker.patch("reconcile.container_registry_mirror.quay.SecretReader")
        mock_engine = mocker.patch(
            "reconcile.container_registry_mirror.quay.MirrorEngine", autospec=True
        )
        mock_engine.return_value.sync.side_effect = ExceptionGroup(
            "skopeo copy failures",
            [SkopeoCmdError("exit code: 1")],
        )
        mocker.patch.object(QuayMirror, "discover_mirrors", return_value=[])

        from reconcile.container_registry_mirror.quay import run

        with pytest.raises(ExceptionGroup) as exc_info:
            run(
                dry_run=True,
                control_file_dir=None,
                compare_tags=False,
                compare_tags_interval=86400,
                repository_urls=None,
                exclude_repository_urls=None,
            )

        assert len(exc_info.value.exceptions) == 1
        assert isinstance(exc_info.value.exceptions[0], SkopeoCmdError)
