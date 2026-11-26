from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from tools.cli_commands.slack_webhooks import (
    SlackWebhookSyncCommand,
    SlackWebhookSyncError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def write_dump(tmp_path: Any, webhooks: dict[str, str]) -> Any:
    path = tmp_path / "slack-webhooks.json"
    path.write_text(json.dumps(webhooks), encoding="utf-8")
    path.chmod(0o600)
    return path


def inventory() -> dict[str, Any]:
    return {
        "slack_workspaces": [
            {
                "name": "redhat-internal",
                "incomingWebhooks": [
                    {
                        "channel": "sd-app-sre-alert",
                        "targets": [
                            {
                                "type": "vault-secret",
                                "path": "app-sre/integrations-input/slack-webhooks",
                                "field": "sd-app-sre-alert",
                                "project": None,
                                "name": None,
                                "variable": None,
                            },
                            {
                                "type": "hcp-terraform-variable-set",
                                "path": None,
                                "field": None,
                                "project": "meta-app-sre",
                                "name": "app-sre-notification-url",
                                "variable": "notification_url",
                            },
                        ],
                    }
                ],
            }
        ]
    }


def query(_query: str) -> dict[str, Any]:
    return inventory()


def no_op_runner(_args: Sequence[str], _input_text: str | None = None) -> str:
    return ""


class FakeRunner:
    def __init__(self, existing_variable: bool = True) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.existing_variable = existing_variable

    def __call__(self, args: Sequence[str], input_text: str | None = None) -> str:
        self.calls.append((list(args), input_text))
        path = args[2]
        if path == "/projects/{project}":
            return json.dumps({"data": {"id": "prj-test"}})
        if path == "/organizations/{organization}/varsets":
            return json.dumps({
                "data": [
                    {
                        "id": "varset-test",
                        "attributes": {"name": "app-sre-notification-url"},
                        "relationships": {"parent": {"data": {"id": "prj-test"}}},
                    }
                ]
            })
        if path == "/varsets/varset-test/relationships/vars":
            variables = (
                [
                    {
                        "id": "var-test",
                        "attributes": {
                            "key": "notification_url",
                            "category": "terraform",
                            "sensitive": True,
                            "hcl": False,
                        },
                    }
                ]
                if self.existing_variable
                else []
            )
            return json.dumps({"data": variables})
        return "{}"


def test_sync_dry_run_does_not_run_commands(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    dump_file = write_dump(
        tmp_path,
        {"#sd-app-sre-alert": "https://hooks.example/test"},
    )

    def fail_runner(args: Sequence[str], input_text: str | None = None) -> str:
        raise AssertionError("dry-run must not execute commands")

    SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=fail_runner,
    ).execute(dump_file, dry_run=True)

    output = capsys.readouterr().out
    assert "[dry-run] sd-app-sre-alert: vault-secret" in output
    assert "[dry-run] sd-app-sre-alert: hcp-terraform-variable-set" in output
    assert "https://hooks.example/test" not in output


def test_sync_updates_vault_and_hcp_variable(tmp_path: Any) -> None:
    dump_file = write_dump(
        tmp_path,
        {"sd-app-sre-alert": "https://hooks.example/test"},
    )
    runner = FakeRunner()
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=False)

    vault_call = next(call for call in runner.calls if call[0][0] == "vault")
    assert vault_call[0] == [
        "vault",
        "kv",
        "patch",
        "app-sre/integrations-input/slack-webhooks",
        "sd-app-sre-alert=-",
    ]
    assert vault_call[1] == "https://hooks.example/test"

    hcp_call = next(
        call for call in runner.calls if call[0][0] == "tfctl" and "-i" in call[0]
    )
    assert "https://hooks.example/test" not in hcp_call[0]
    assert json.loads(hcp_call[1] or "") == {
        "data": {
            "id": "var-test",
            "type": "vars",
            "attributes": {"value": "https://hooks.example/test"},
        }
    }


def test_sync_creates_missing_hcp_variable(tmp_path: Any) -> None:
    dump_file = write_dump(
        tmp_path,
        {"sd-app-sre-alert": "https://hooks.example/test"},
    )
    runner = FakeRunner(existing_variable=False)
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=False)

    hcp_call = next(
        call for call in runner.calls if call[0][0] == "tfctl" and "-i" in call[0]
    )
    assert hcp_call[0] == [
        "tfctl",
        "api",
        "/varsets/varset-test/relationships/vars",
        "-X",
        "POST",
        "-i",
        "-",
    ]
    assert json.loads(hcp_call[1] or "") == {
        "data": {
            "type": "vars",
            "attributes": {
                "key": "notification_url",
                "value": "https://hooks.example/test",
                "category": "terraform",
                "sensitive": True,
                "hcl": False,
            },
        }
    }


def test_rejects_invalid_dump_url(tmp_path: Any) -> None:
    dump_file = write_dump(
        tmp_path,
        {"sd-app-sre-alert": "http://hooks.example/test"},
    )
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=no_op_runner,
    )

    with pytest.raises(SlackWebhookSyncError, match="invalid URL"):
        command.execute(dump_file, dry_run=True)


def test_rejects_dump_file_readable_by_others(tmp_path: Any) -> None:
    dump_file = write_dump(
        tmp_path,
        {"sd-app-sre-alert": "https://hooks.example/test"},
    )
    dump_file.chmod(0o644)
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=no_op_runner,
    )

    with pytest.raises(SlackWebhookSyncError, match="readable by group or other"):
        command.execute(dump_file, dry_run=True)
