from __future__ import annotations

import os
import tempfile
from subprocess import CompletedProcess
from typing import TYPE_CHECKING

import pytest

from reconcile.utils import lean_terraform_client

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_state_rm_access_key_skips_second_removal(mocker: MockerFixture) -> None:
    command = mocker.patch.object(
        lean_terraform_client,
        "_terraform_command",
        side_effect=[
            (0, "", ""),  # init
            (0, "aws_iam_access_key.service-user\n", ""),
            (0, "", ""),  # rm
            (0, "", ""),  # init on the next reconciliation
            (0, "", ""),  # the old key ID is now absent
        ],
    )

    for _ in range(2):
        assert lean_terraform_client.state_rm_access_key(
            {"account": "workdir"}, "account", "service-user", "old-key-id"
        )

    init = mocker.call(
        args=["terraform", "init", "-input=false", "-no-color"],
        working_dir="workdir",
        env=None,
    )
    lookup = mocker.call(["terraform", "state", "list", "-id=old-key-id"], "workdir")
    remove = mocker.call(
        ["terraform", "state", "rm", "-no-color", "aws_iam_access_key.service-user"],
        "workdir",
    )
    assert command.call_args_list == [init, lookup, remove, init, lookup]


@pytest.mark.parametrize(
    "responses",
    [
        [(1, "", "init error")],
        [(0, "", ""), (1, "", "backend error")],
        [(0, "", ""), (0, "aws_iam_access_key.other-user\n", "")],
        [
            (0, "", ""),
            (0, "aws_iam_access_key.service-user\n", ""),
            (1, "", "rm error"),
        ],
    ],
    ids=["init-failure", "state-read-failure", "unexpected-address", "removal-failure"],
)
def test_state_rm_access_key_reports_failures(
    mocker: MockerFixture, responses: list[tuple[int, str, str]]
) -> None:
    command = mocker.patch.object(
        lean_terraform_client, "_terraform_command", side_effect=responses
    )

    assert not lean_terraform_client.state_rm_access_key(
        {"account": "workdir"}, "account", "service-user", "old-key-id"
    )
    assert command.call_count == len(responses)


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
        with open(os.path.join(working_dir, "main.tf"), "w", encoding="locale"):
            pass
        assert lean_terraform_client.init(working_dir)[0] == 0
        assert lean_terraform_client.output(working_dir)[0] == 0
        assert lean_terraform_client.plan(working_dir, "tfplan")[0] == 0
        assert lean_terraform_client.show_json(working_dir, "tfplan") is not None
        assert lean_terraform_client.apply(working_dir, "tfplan")[0] == 0
