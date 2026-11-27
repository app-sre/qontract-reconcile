from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

from tools.cli_commands.slack_webhooks import (
    SlackWebhookSyncCommand,
    SlackWebhookSyncError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


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
        ],
    }


def query(_query: str) -> dict[str, Any]:
    return inventory()


def conflicting_hcp_query(_query: str) -> dict[str, Any]:
    payload = inventory()
    webhooks = payload["slack_workspaces"][0]["incomingWebhooks"]
    webhooks[0]["channel"] = "channel-a"
    webhooks[0]["targets"][0]["field"] = "channel-a"
    conflicting = deepcopy(webhooks[0])
    conflicting["channel"] = "channel-b"
    conflicting["targets"][0]["field"] = "channel-b"
    webhooks.append(conflicting)
    return payload


def no_op_runner(
    _args: Sequence[str],
    _input_text: str | None = None,
    _env: Mapping[str, str] | None = None,
) -> str:
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
        hcl: bool = False,
        vault_secret: dict[str, str] | None = None,
        vault_version: int = 1,
    ) -> None:
        self.calls: list[tuple[list[str], str | None, Mapping[str, str] | None]] = []
        self.existing_variable = existing_variable
        self.hcl = hcl
        self.vault_secret = vault_secret if vault_secret is not None else {}
        self.vault_version = vault_version
        self.vault_patches: list[
            tuple[str, dict[str, str], Mapping[str, str] | None]
        ] = []
        self.vault_puts: list[tuple[str, dict[str, str], Mapping[str, str] | None]] = []

    def __call__(
        self,
        args: Sequence[str],
        input_text: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        self.calls.append((list(args), input_text, env))
        if args[0] == "vault":
            if args[1] == "kv" and args[2] == "get":
                if self.vault_version == 1:
                    return json.dumps({"data": self.vault_secret})
                return json.dumps({
                    "data": {
                        "data": self.vault_secret,
                        "metadata": {"version": 1},
                    }
                })
            if args[1] == "kv" and args[2] == "patch":
                patch_data = json.loads(input_text or "{}")
                self.vault_patches.append((args[3], patch_data, env))
                self.vault_secret.update(patch_data)
                return ""
            if args[1] == "kv" and args[2] == "put":
                put_data = json.loads(input_text or "{}")
                self.vault_puts.append((args[3], put_data, env))
                self.vault_secret.update(put_data)
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
                            "hcl": self.hcl,
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
        vault_address="https://vault.example.com",
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
    assert "unchanged vault-secret" not in output

    assert runner.vault_patches == []
    assert runner.vault_puts == []
    mutating_calls = [
        call for call in runner.calls if call[0][0] == "tfctl" and "-X" in call[0]
    ]
    assert mutating_calls == []


def test_sync_updates_vault_and_hcp_variable(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(vault_secret={"unrelated": "secret"})
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=False)

    assert runner.vault_puts == [
        (
            "app-sre/integrations-input/slack-webhooks",
            {"unrelated": "secret", **webhook_dump()},
            {"VAULT_ADDR": "https://vault.example.com"},
        )
    ]
    assert runner.vault_patches == []

    vault_call = next(
        call for call in runner.calls if call[0][0] == "vault" and call[0][2] == "put"
    )
    assert vault_call[0][1:] == [
        "kv",
        "put",
        "app-sre/integrations-input/slack-webhooks",
        "-",
    ]
    assert vault_call[1] is not None
    assert vault_call[2] == {"VAULT_ADDR": "https://vault.example.com"}

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


def test_rejects_conflicting_hcp_destination_before_vault_update(
    tmp_path: Any,
) -> None:
    dump_file = write_dump(
        tmp_path,
        {
            "channel-a": "https://hooks.example/a",
            "channel-b": "https://hooks.example/b",
            "sd-app-sre-alert-stg": "https://hooks.example/test-stg",
        },
    )
    runner = FakeRunner()
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=conflicting_hcp_query,
        vault_address="https://vault.example.com",
        command_runner=runner,
    )

    with pytest.raises(
        SlackWebhookSyncError,
        match="HCP variable set target has conflicting webhook URLs",
    ):
        command.execute(dump_file, dry_run=False)

    assert runner.vault_patches == []
    assert runner.vault_puts == []


def test_rejects_invalid_hcp_variable_before_vault_update(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(hcl=True)
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=runner,
    )

    with pytest.raises(
        SlackWebhookSyncError, match="HCP variable has unexpected metadata"
    ):
        command.execute(dump_file, dry_run=False)

    assert runner.vault_patches == []
    assert runner.vault_puts == []


def test_sync_skips_unchanged_vault_secret(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(vault_secret=webhook_dump())
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=False)

    assert runner.vault_patches == []
    assert runner.vault_puts == []


def test_dry_run_reports_unchanged_vault_secret_without_mutating(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(vault_secret=webhook_dump())
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=True)

    output = capsys.readouterr().out
    assert (
        "[dry-run] unchanged vault-secret "
        "app-sre/integrations-input/slack-webhooks: "
        "sd-app-sre-alert, sd-app-sre-alert-stg" in output
    )
    assert "would update vault-secret" not in output
    assert runner.vault_patches == []
    assert runner.vault_puts == []


def test_dry_run_shows_only_changed_vault_fields(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(
        vault_secret={
            "sd-app-sre-alert": "https://hooks.example/old",
            "sd-app-sre-alert-stg": "https://hooks.example/test-stg",
        }
    )
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=True)

    output = capsys.readouterr().out
    assert (
        "[dry-run] would update vault-secret "
        "app-sre/integrations-input/slack-webhooks: sd-app-sre-alert" in output
    )
    assert "sd-app-sre-alert-stg" not in output


def test_sync_patches_v2_vault_secret(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(
        vault_secret={"unrelated": "secret"},
        vault_version=2,
    )
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=runner,
    )

    command.execute(dump_file, dry_run=False)

    assert runner.vault_patches == [
        (
            "app-sre/integrations-input/slack-webhooks",
            webhook_dump(),
            {"VAULT_ADDR": "https://vault.example.com"},
        )
    ]
    assert runner.vault_puts == []


def test_sync_creates_missing_hcp_variable(tmp_path: Any) -> None:
    dump_file = write_dump(tmp_path, webhook_dump())
    runner = FakeRunner(existing_variable=False)
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
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


@pytest.mark.parametrize("url", [None, 1])
def test_rejects_non_string_dump_url(tmp_path: Any, url: Any) -> None:
    dump_file = write_dump(tmp_path, {"sd-app-sre-alert": url})
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=no_op_runner,
    )

    with pytest.raises(
        SlackWebhookSyncError, match="dump file entries must be strings"
    ):
        command.execute(dump_file, dry_run=True)


@pytest.mark.parametrize("url", ["", "http://hooks.example/test", "hooks.example/test"])
def test_rejects_invalid_dump_webhook_url(tmp_path: Any, url: str) -> None:
    dump_file = write_dump(
        tmp_path,
        {
            "sd-app-sre-alert": url,
            "sd-app-sre-alert-stg": "https://hooks.example/test-stg",
        },
    )
    command = SlackWebhookSyncCommand(
        workspace="redhat-internal",
        query_func=query,
        vault_address="https://vault.example.com",
        command_runner=no_op_runner,
    )

    with pytest.raises(SlackWebhookSyncError, match="invalid webhook URL for channel"):
        command.execute(dump_file, dry_run=True)
