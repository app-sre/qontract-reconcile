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
                    },
                    {
                        "channel": "sd-app-sre-alert-stg",
                        "targets": [
                            {
                                "type": "vault-secret",
                                "path": "app-sre/integrations-input/slack-webhooks",
                                "field": "sd-app-sre-alert-stg",
                                "project": None,
                                "name": None,
                                "variable": None,
                            }
                        ],
                    },
                ],
            }
        ]
    }


def query(_query: str) -> dict[str, Any]:
    return inventory()


def no_op_runner(_args: Sequence[str], _input_text: str | None = None) -> str:
    return ""


def webhook_dump() -> dict[str, str]:
    return {
        "sd-app-sre-alert": "https://hooks.example/test",
        "sd-app-sre-alert-stg": "https://hooks.example/test-stg",
    }


class FakeRunner:
    def __init__(
        self,
        existing_variable: bool = True,
        vault_secret: dict[str, str] | None = None,
    ) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.existing_variable = existing_variable
        self.vault_patches: list[tuple[str, dict[str, str]]] = []
        self.vault_secret = vault_secret if vault_secret is not None else {}

    def __call__(self, args: Sequence[str], input_text: str | None = None) -> str:
        self.calls.append((list(args), input_text))
        if args[0] == "vault":
            if args[1] == "kv" and args[2] == "get":
                return json.dumps({"data": {"data": self.vault_secret}})
            if args[1] == "kv" and args[2] == "patch":
                body = json.loads(input_text or "{}")
                self.vault_patches.append((args[3], body))
                self.vault_secret.update(body)
                return ""

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


def test_sync_dry_run_shows_planned_writes_without_mutating(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner()
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=True)

    output = capsys.readouterr().out
    assert (
        "[dry-run] would update vault-secret "
        "app-sre/integrations-input/slack-webhooks: "
        "sd-app-sre-alert, sd-app-sre-alert-stg" in output
    )
    assert (
        "[dry-run] would update sd-app-sre-alert: "
        "hcp-terraform-variable-set "
        "meta-app-sre/app-sre-notification-url/notification_url "
        "(PATCH /vars/var-test)" in output
    )
    assert "https://hooks.example/test" not in output

    assert runner.vault_patches == []
    mutating_calls = [
        call for call in runner.calls if call[0][0] == "tfctl" and "-X" in call[0]
    ]
    assert mutating_calls == []


def test_sync_updates_vault_and_hcp_variable(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner()
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=False)

    assert len(runner.vault_patches) == 1
    path, body = runner.vault_patches[0]
    assert path == "app-sre/integrations-input/slack-webhooks"
    assert body == webhook_dump()

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


def test_sync_skips_unchanged_vault_secret(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(vault_secret=webhook_dump())
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=False)

    assert runner.vault_patches == []


def test_sync_creates_missing_hcp_variable(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
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


def test_reads_dump_file_without_permission_check(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    dump_file.chmod(0o644)
    assert dump_file.stat().st_mode & 0o044

    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        command_runner=FakeRunner(vault_secret=webhook_dump()),
    )

    command.execute(dump_file, dry_run=True)
