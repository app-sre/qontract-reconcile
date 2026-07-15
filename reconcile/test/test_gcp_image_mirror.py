from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile.container_registry_mirror.gcp import GcpMirror

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class TestModuleLevelRun:
    """The module-level run() function wires together the GcpMirror
    implementation and MirrorEngine."""

    def test_run_calls_engine_sync(self, mocker: MockerFixture) -> None:
        mocker.patch("reconcile.container_registry_mirror.gcp.gql")
        mocker.patch("reconcile.container_registry_mirror.gcp.queries")
        mocker.patch("reconcile.container_registry_mirror.gcp.SecretReader")
        mocker.patch("reconcile.container_registry_mirror.gcp.gql_gcp_projects")
        mock_engine = mocker.patch(
            "reconcile.container_registry_mirror.gcp.MirrorEngine", autospec=True
        )
        mocker.patch.object(GcpMirror, "discover_mirrors", return_value=[])

        from reconcile.container_registry_mirror.gcp import run

        run(dry_run=True)

        mock_engine.return_value.sync.assert_called_once_with([])

    def test_run_raises_exception_group_on_engine_error(
        self, mocker: MockerFixture
    ) -> None:
        mocker.patch("reconcile.container_registry_mirror.gcp.gql")
        mocker.patch("reconcile.container_registry_mirror.gcp.queries")
        mocker.patch("reconcile.container_registry_mirror.gcp.SecretReader")
        mocker.patch("reconcile.container_registry_mirror.gcp.gql_gcp_projects")
        mock_engine = mocker.patch(
            "reconcile.container_registry_mirror.gcp.MirrorEngine", autospec=True
        )
        mock_engine.return_value.sync.side_effect = ExceptionGroup(
            "skopeo copy failures",
            [SkopeoCmdError("exit code: 1")],
        )
        mocker.patch.object(GcpMirror, "discover_mirrors", return_value=[])

        from reconcile.container_registry_mirror.gcp import run

        with pytest.raises(ExceptionGroup) as exc_info:
            run(dry_run=True)

        assert len(exc_info.value.exceptions) == 1
        assert isinstance(exc_info.value.exceptions[0], SkopeoCmdError)
