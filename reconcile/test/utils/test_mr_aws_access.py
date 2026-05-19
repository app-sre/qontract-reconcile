from pathlib import Path
from unittest.mock import create_autospec

from gitlab.v4.objects import Project

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.aws_access import CreateDeleteAwsAccessKey

RAW_FILE = b"""\
---
$schema: /aws/account-1.yml
name: test-account
deleteKeys: []
"""

RAW_FILE_NO_DELETE_KEYS = b"""\
---
$schema: /aws/account-1.yml
name: test-account
"""


def _make_mr(
    account: str = "test-account",
    path: str = "/data/aws/account.yml",
    key: str = "AKIAIOSFODNN7EXAMPLE",
) -> CreateDeleteAwsAccessKey:
    mr = CreateDeleteAwsAccessKey(account=account, path=path, key=key)
    mr.branch = "test-branch"
    return mr


def test_process_appends_key_to_delete_keys() -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = RAW_FILE

    mr = _make_mr()
    mr.process(cli)

    cli.update_file.assert_called_once()
    call_kwargs = cli.update_file.call_args[1]
    assert "AKIAIOSFODNN7EXAMPLE" in call_kwargs["content"]
    assert call_kwargs["content"].startswith("---\n")
    assert call_kwargs["branch_name"] == "test-branch"

    cli.create_file.assert_called_once()
    create_kwargs = cli.create_file.call_args[1]
    assert create_kwargs["file_path"] == str(
        Path("data")
        / "app-interface"
        / "emails"
        / "test-account-AKIAIOSFODNN7EXAMPLE.yml"
    )


def test_process_creates_delete_keys_if_missing() -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = RAW_FILE_NO_DELETE_KEYS

    mr = _make_mr()
    mr.process(cli)

    call_kwargs = cli.update_file.call_args[1]
    assert "deleteKeys" in call_kwargs["content"]
    assert "AKIAIOSFODNN7EXAMPLE" in call_kwargs["content"]
