import os
import tempfile

import pytest

from reconcile.quay_mirror import QuayMirror, CONTROL_FILE_NAME


def test_check_compare_tags_no_control_file():
    assert QuayMirror.check_compare_tags_elapsed_time("/no-such-file", 100)


def test_check_compare_tags_with_file(mocker):
    now = 1662124612.995397
    mocker.patch("time.time", return_value=now)

    with tempfile.NamedTemporaryFile() as fp:
        fp.write(str(now - 100.0).encode())
        fp.seek(0)

        assert QuayMirror.check_compare_tags_elapsed_time(fp.name, 10)
        assert not QuayMirror.check_compare_tags_elapsed_time(fp.name, 1000)


def test_control_file_dir_does_not_exist(mocker):
    mocker.patch("reconcile.utils.gql.get_api", autospec=True)
    mocker.patch("reconcile.queries.get_app_interface_settings", return_value={})

    with pytest.raises(FileNotFoundError):
        QuayMirror(control_file_dir="/no-such-dir")


def test_control_file_path_from_given_dir(mocker):
    mocker.patch("reconcile.utils.gql.get_api", autospec=True)
    mocker.patch("reconcile.queries.get_app_interface_settings", return_value={})

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        qm = QuayMirror(control_file_dir=tmp_dir_name)
        assert qm.control_file_path == os.path.join(tmp_dir_name, CONTROL_FILE_NAME)


def test_is_compare_tags(mocker):
    now = 1662124612.995397
    mocker.patch("time.time", return_value=now)
    mocker.patch("reconcile.utils.gql.get_api", autospec=True)
    mocker.patch("reconcile.queries.get_app_interface_settings", return_value={})

    with tempfile.TemporaryDirectory() as tmp_dir_name:
        with open(os.path.join(tmp_dir_name, CONTROL_FILE_NAME), "w") as fh:
            fh.write(str(now - 100.0))

        qm = QuayMirror(control_file_dir=tmp_dir_name, compare_tags_interval=1000)
        assert not qm.is_compare_tags

        qm = QuayMirror(
            control_file_dir=tmp_dir_name,
            compare_tags_interval=10,
            force_compare_tags=True,
        )
        assert qm.is_compare_tags
