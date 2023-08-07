import os
import tempfile
from subprocess import CompletedProcess

from pytest_mock import MockerFixture

from reconcile.utils import lean_terraform_client


def test_init(mocker: MockerFixture) -> None:
    mocker.patch(
        "reconcile.utils.lean_terraform_client.os"
    ).environ.copy.return_value = {}
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    mocked_subprocess.run.return_value = CompletedProcess(
        args=[],
        returncode=0,
        stdout=b"out",
        stderr=b"err",
    )

    return_code, stdout, stderr = lean_terraform_client.init(
        "working_dir",
        env={"TF_LOG": "INFO"},
    )

    assert return_code == 0
    assert stdout == "out"
    assert stderr == "err"
    mocked_subprocess.run.assert_called_once_with(
        ["terraform", "init", "-input=false", "-no-color"],
        capture_output=True,
        check=False,
        cwd="working_dir",
        env={"TF_LOG": "INFO"},
    )


def test_output(mocker: MockerFixture) -> None:
    mocker.patch(
        "reconcile.utils.lean_terraform_client.os"
    ).environ.copy.return_value = {}
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    mocked_subprocess.run.return_value = CompletedProcess(
        args=[],
        returncode=0,
        stdout=b"out",
        stderr=b"err",
    )

    return_code, stdout, stderr = lean_terraform_client.output(
        "working_dir",
        env={"TF_LOG": "INFO"},
    )

    assert return_code == 0
    assert stdout == "out"
    assert stderr == "err"
    mocked_subprocess.run.assert_called_once_with(
        ["terraform", "output", "-json"],
        capture_output=True,
        check=False,
        cwd="working_dir",
        env={"TF_LOG": "INFO"},
    )


def test_plan(mocker: MockerFixture) -> None:
    mocker.patch(
        "reconcile.utils.lean_terraform_client.os"
    ).environ.copy.return_value = {}
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    mocked_subprocess.run.return_value = CompletedProcess(
        args=[],
        returncode=0,
        stdout=b"out",
        stderr=b"err",
    )

    return_code, stdout, stderr = lean_terraform_client.plan(
        working_dir="working_dir",
        out="tfplan",
        env={"TF_LOG": "INFO"},
    )

    assert return_code == 0
    assert stdout == "out"
    assert stderr == "err"
    mocked_subprocess.run.assert_called_once_with(
        [
            "terraform",
            "plan",
            "-out=tfplan",
            "-input=false",
            "-no-color",
        ],
        capture_output=True,
        check=False,
        cwd="working_dir",
        env={"TF_LOG": "INFO"},
    )


def test_apply(mocker: MockerFixture) -> None:
    mocker.patch(
        "reconcile.utils.lean_terraform_client.os"
    ).environ.copy.return_value = {}
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    mocked_subprocess.run.return_value = CompletedProcess(
        args=[],
        returncode=0,
        stdout=b"out",
        stderr=b"err",
    )

    return_code, stdout, stderr = lean_terraform_client.apply(
        working_dir="working_dir",
        dir_or_plan="tfplan",
        env={"TF_LOG": "INFO"},
    )

    assert return_code == 0
    assert stdout == "out"
    assert stderr == "err"
    mocked_subprocess.run.assert_called_once_with(
        [
            "terraform",
            "apply",
            "-input=false",
            "-no-color",
            "tfplan",
        ],
        capture_output=True,
        check=False,
        cwd="working_dir",
        env={"TF_LOG": "INFO"},
    )


def test_show_json(mocker: MockerFixture) -> None:
    mocker.patch(
        "reconcile.utils.lean_terraform_client.os"
    ).environ.copy.return_value = {}
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    mocked_subprocess.run.return_value = CompletedProcess(
        args=[],
        returncode=0,
        stdout=b"{}",
        stderr=b"",
    )

    result = lean_terraform_client.show_json(
        working_dir="working_dir",
        path="tfplan",
    )

    assert result == {}
    mocked_subprocess.run.assert_called_once_with(
        [
            "terraform",
            "show",
            "-no-color",
            "-json",
            "tfplan",
        ],
        capture_output=True,
        check=False,
        cwd="working_dir",
        env={},
    )


def test_terraform_component() -> None:
    with tempfile.TemporaryDirectory() as working_dir:
        with open(os.path.join(working_dir, "main.tf"), "w"):
            pass
        assert lean_terraform_client.init(working_dir)[0] == 0
        assert lean_terraform_client.output(working_dir)[0] == 0
        assert lean_terraform_client.plan(working_dir, "tfplan")[0] == 0
        assert lean_terraform_client.show_json(working_dir, "tfplan") is not None
        assert lean_terraform_client.apply(working_dir, "tfplan")[0] == 0
