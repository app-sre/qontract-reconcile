import re
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import MagicMock, create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.binary import binary, binary_version


def test_binary_when_exist(mocker: MockerFixture) -> None:
    mock_shutil_which = mocker.patch(
        "reconcile.utils.binary.shutil.which",
        return_value="/usr/bin/some-binary",
    )
    mock_func = MagicMock()
    decorated = binary(binaries=["some-binary"])(mock_func)

    decorated("arg1", kwarg1="value1")

    mock_func.assert_called_once_with("arg1", kwarg1="value1")
    mock_shutil_which.assert_called_once_with("some-binary")


def test_binary_when_missing(mocker: MockerFixture) -> None:
    mock_shutil_which = mocker.patch(
        "reconcile.utils.binary.shutil.which",
        return_value=None,
    )
    mock_func = MagicMock()
    decorated = binary(binaries=["some-binary"])(mock_func)

    with pytest.raises(
        Exception,
        match=r"Aborting: Could not find binary: some-binary. Hint: https://command-not-found.com/some-binary",
    ):
        decorated("arg1", kwarg1="value1")

    mock_func.assert_not_called()
    mock_shutil_which.assert_called_once_with("some-binary")


@pytest.mark.parametrize(
    ("result_stdout", "search_regex", "expected_versions"),
    [
        (
            b"version: 1.2.3\n",
            r"^version: (\d+\.\d+\.\d+)$",
            ["1.2.3"],
        ),
        (
            b"version: 1.2.3\n",
            r"^version: (\d+\.\d+\.\d+)$",
            ["1.0.0", "1.2.3"],
        ),
        (
            b"some output\nversion 1.2.3\nmore output\n",
            r"^version (\d+\.\d+\.\d+)$",
            ["1.2.3"],
        ),
    ],
)
def test_binary_version_when_match(
    mocker: MockerFixture,
    result_stdout: bytes,
    search_regex: str,
    expected_versions: list[str],
) -> None:
    mock_result = create_autospec(CompletedProcess, stdout=result_stdout)
    mock_subprocess_run = mocker.patch(
        "reconcile.utils.binary.subprocess.run",
        return_value=mock_result,
    )
    mock_func = MagicMock()
    decorated = binary_version(
        binary="some-binary",
        version_args=["--version"],
        search_regex=search_regex,
        expected_versions=expected_versions,
    )(mock_func)

    decorated("arg1", kwarg1="value1")

    mock_subprocess_run.assert_called_once_with(
        ["some-binary", "--version"],
        capture_output=True,
        check=True,
    )
    mock_func.assert_called_once_with("arg1", kwarg1="value1")


def test_binary_version_when_binary_missing(
    mocker: MockerFixture,
) -> None:
    mock_subprocess_run = mocker.patch("reconcile.utils.binary.subprocess.run")
    mock_subprocess_run.side_effect = CalledProcessError(-1, "some-binary --version")
    mock_func = MagicMock()
    decorated = binary_version(
        binary="some-binary",
        version_args=["--version"],
        search_regex=r"version (\d+\.\d+\.\d+)",
        expected_versions=["1.0.0"],
    )(mock_func)

    with pytest.raises(
        Exception,
        match=r"Could not execute binary 'some-binary' for binary version check: ",
    ):
        decorated("arg1", kwarg1="value1")

    mock_subprocess_run.assert_called_once_with(
        ["some-binary", "--version"],
        capture_output=True,
        check=True,
    )
    mock_func.assert_not_called()


def test_binary_version_when_regex_not_match(mocker: MockerFixture) -> None:
    mock_result = create_autospec(
        CompletedProcess,
        stdout=b"no version info here\n",
    )
    mock_subprocess_run = mocker.patch(
        "reconcile.utils.binary.subprocess.run",
        return_value=mock_result,
    )
    mock_func = MagicMock()
    decorated = binary_version(
        binary="some-binary",
        version_args=["--version"],
        search_regex=r"version (\d+\.\d+\.\d+)",
        expected_versions=["1.0.0"],
    )(mock_func)

    with pytest.raises(
        Exception,
        match=re.escape(
            r"Could not find version for binary 'some-binary' via regex for binary version check: regex did not match: 'version (\d+\.\d+\.\d+)'"
        ),
    ):
        decorated("arg1", kwarg1="value1")

    mock_subprocess_run.assert_called_once_with(
        ["some-binary", "--version"],
        capture_output=True,
        check=True,
    )
    mock_func.assert_not_called()


def test_binary_version_when_unexpected_version(mocker: MockerFixture) -> None:
    mock_result = create_autospec(
        CompletedProcess,
        stdout=b"version 1.0.0\n",
    )
    mock_subprocess_run = mocker.patch(
        "reconcile.utils.binary.subprocess.run",
        return_value=mock_result,
    )
    mock_func = MagicMock()
    decorated = binary_version(
        binary="some-binary",
        version_args=["--version"],
        search_regex=r"version (\d+\.\d+\.\d+)",
        expected_versions=["1.2.3"],
    )(mock_func)

    with pytest.raises(
        Exception,
        match=re.escape(
            r"Binary version check for binary some-binary failed! Expected: ['1.2.3'], found: 1.0.0"
        ),
    ):
        decorated("arg1", kwarg1="value1")

    mock_subprocess_run.assert_called_once_with(
        ["some-binary", "--version"], capture_output=True, check=True
    )
    mock_func.assert_not_called()
