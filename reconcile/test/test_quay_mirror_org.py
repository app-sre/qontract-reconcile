from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from reconcile.quay_mirror_org import (
    CONTROL_FILE_NAME,
    QuayMirrorOrg,
)

if TYPE_CHECKING:
    from unittest.mock import Mock

    from pytest_mock import MockerFixture

NOW = 1662124612.995397


@patch("reconcile.utils.gql.get_api", autospec=True)
@patch("reconcile.queries.get_app_interface_settings", return_value={})
@patch("reconcile.quay_base.get_quay_api_store", return_value={})
class TestControlFile:
    def test_control_file_dir_does_not_exist(
        self, mock_gql: Mock, mock_settings: Mock, mock_quay_api_store: Mock
    ) -> None:
        with pytest.raises(FileNotFoundError):
            QuayMirrorOrg(control_file_dir="/no-such-dir")

    def test_control_file_path_from_given_dir(
        self, mock_gql: Mock, mock_settings: Mock, mock_quay_api_store: Mock
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_name:
            qm = QuayMirrorOrg(control_file_dir=tmp_dir_name)
            assert qm.control_file_path == os.path.join(tmp_dir_name, CONTROL_FILE_NAME)


@patch("reconcile.utils.gql.get_api", autospec=True)
@patch("reconcile.queries.get_app_interface_settings", return_value={})
@patch("reconcile.quay_base.get_quay_api_store", return_value={})
@patch("time.time", return_value=NOW)
class TestIsCompareTags:
    def setup_method(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        with open(
            os.path.join(self.tmp_dir.name, CONTROL_FILE_NAME), "w", encoding="locale"
        ) as fh:
            fh.write(str(NOW - 100.0))

    def teardown_method(self) -> None:
        self.tmp_dir.cleanup()

    # Last run was in NOW - 100s, we run compare tags every 10s.
    def test_is_compare_tags_elapsed(
        self,
        mock_gql: Mock,
        mock_settings: Mock,
        mock_time: Mock,
        mock_quay_api_store: Mock,
    ) -> None:
        qm = QuayMirrorOrg(control_file_dir=self.tmp_dir.name, compare_tags_interval=10)
        assert qm.is_compare_tags

    # Same as before, but now we force no compare with the option.
    def test_is_compare_tags_force_no_compare(
        self,
        mock_gql: Mock,
        mock_settings: Mock,
        mock_time: Mock,
        mock_quay_api_store: Mock,
    ) -> None:
        qm = QuayMirrorOrg(
            control_file_dir=self.tmp_dir.name,
            compare_tags_interval=10,
            compare_tags=False,
        )
        assert not qm.is_compare_tags

    # Last run was in NOW - 100s, we run compare tags every 1000s.
    def test_is_compare_tags_not_elapsed(
        self,
        mock_gql: Mock,
        mock_settings: Mock,
        mock_time: Mock,
        mock_quay_api_store: Mock,
    ) -> None:
        qm = QuayMirrorOrg(
            control_file_dir=self.tmp_dir.name, compare_tags_interval=1000
        )
        assert not qm.is_compare_tags

    # Same as before, but now we force compare with the option.
    def test_is_compare_tags_force_compare(
        self,
        mock_gql: Mock,
        mock_settings: Mock,
        mock_time: Mock,
        mock_quay_api_store: Mock,
    ) -> None:
        qm = QuayMirrorOrg(
            control_file_dir=self.tmp_dir.name,
            compare_tags_interval=1000,
            compare_tags=True,
        )
        assert qm.is_compare_tags


def test_quay_mirror_org_session(mocker: MockerFixture) -> None:
    mocked_request = mocker.patch("reconcile.quay_mirror_org.requests")

    with (
        patch("reconcile.quay_base.get_quay_api_store", return_value={}),
        QuayMirrorOrg() as quay_mirror_org,
    ):
        assert quay_mirror_org.session == mocked_request.Session.return_value

    mocked_request.Session.return_value.close.assert_called_once_with()
