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


def test_state_update_access_key_status_success(mocker: MockerFixture) -> None:
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    mocked_subprocess.run.return_value = CompletedProcess(
        args=[],
        returncode=0,
        stdout=b"Success",
        stderr=b"",
    )

    working_dirs = {"account1": "/path/to/account1", "account2": "/path/to/account2"}
    keys_by_account = {
        "account1": [
            {"user": "user1", "key_id": "AKIA123", "status": "Inactive"},
            {"user": "user2", "key_id": "AKIA456", "status": "Inactive"},
        ],
        "account2": [{"user": "user3", "key_id": "AKIA789", "status": "Inactive"}],
    }

    result = lean_terraform_client.state_update_access_key_status(
        working_dirs, keys_by_account
    )

    assert result is True
    # Should have called terraform init for each account
    init_calls = [
        call for call in mocked_subprocess.run.call_args_list if call[0][0][1] == "init"
    ]
    assert len(init_calls) == 2

    # Should have called terraform import for each key
    import_calls = [
        call
        for call in mocked_subprocess.run.call_args_list
        if call[0][0][1] == "import"
    ]
    assert len(import_calls) == 3


def test_state_update_access_key_status_init_failure(mocker: MockerFixture) -> None:
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    # First call (init) fails, subsequent calls succeed
    mocked_subprocess.run.side_effect = [
        CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"Init failed"),
        CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b""),
        CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b""),
    ]

    working_dirs = {"account1": "/path/to/account1", "account2": "/path/to/account2"}
    keys_by_account = {
        "account1": [{"user": "user1", "key_id": "AKIA123", "status": "Inactive"}],
        "account2": [{"user": "user2", "key_id": "AKIA456", "status": "Inactive"}],
    }

    result = lean_terraform_client.state_update_access_key_status(
        working_dirs, keys_by_account
    )

    assert result is False


def test_state_update_access_key_status_import_failure(mocker: MockerFixture) -> None:
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")
    # Init succeeds, import fails
    mocked_subprocess.run.side_effect = [
        CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b""),  # init
        CompletedProcess(
            args=[], returncode=1, stdout=b"", stderr=b"Import failed"
        ),  # import
    ]

    working_dirs = {"account1": "/path/to/account1"}
    keys_by_account = {
        "account1": [{"user": "user1", "key_id": "AKIA123", "status": "Inactive"}]
    }

    result = lean_terraform_client.state_update_access_key_status(
        working_dirs, keys_by_account
    )

    assert result is False


def test_state_update_access_key_status_empty_keys(mocker: MockerFixture) -> None:
    mocked_subprocess = mocker.patch("reconcile.utils.lean_terraform_client.subprocess")

    working_dirs = {"account1": "/path/to/account1"}
    keys_by_account: dict[str, list[dict[str, str]]] = {"account1": []}

    result = lean_terraform_client.state_update_access_key_status(
        working_dirs, keys_by_account
    )

    assert result is True
    # Should not have called any terraform commands
    mocked_subprocess.run.assert_not_called()


def test_terraform_component() -> None:
    with tempfile.TemporaryDirectory() as working_dir:
        with open(os.path.join(working_dir, "main.tf"), "w", encoding="locale"):
            pass
        assert lean_terraform_client.init(working_dir)[0] == 0
        assert lean_terraform_client.output(working_dir)[0] == 0
        assert lean_terraform_client.plan(working_dir, "tfplan")[0] == 0
        assert lean_terraform_client.show_json(working_dir, "tfplan") is not None
        assert lean_terraform_client.apply(working_dir, "tfplan")[0] == 0
