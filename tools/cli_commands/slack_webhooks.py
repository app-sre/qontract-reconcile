from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from reconcile.typed_queries.slack_webhooks import get_slack_webhooks

if TYPE_CHECKING:
    from pathlib import Path

    from reconcile.gql_definitions.slack_webhooks.slack_webhooks import (
        SlackWorkspaceIncomingWebhookTargetV1,
    )


class SlackWebhookSyncError(Exception):
    pass


@dataclass(frozen=True)
class VaultTarget:
    path: str
    field: str

    def __str__(self) -> str:
        return f"vault-secret {self.path}/{self.field}"


@dataclass(frozen=True)
class VaultSecretState:
    data: dict[str, Any]
    version: int


@dataclass(frozen=True)
class VaultChange:
    changed: dict[str, str]
    state: VaultSecretState


@dataclass(frozen=True)
class HcpTerraformVariableSetTarget:
    project: str
    name: str
    variable: str

    def __str__(self) -> str:
        return f"hcp-terraform-variable-set {self.project}/{self.name}/{self.variable}"


@dataclass(frozen=True)
class HcpTerraformVariableSetChange:
    method: str
    path: str


@dataclass(frozen=True)
class HcpTerraformVariableSetUpdate:
    channel: str
    target: HcpTerraformVariableSetTarget
    url: str
    change: HcpTerraformVariableSetChange


Target = VaultTarget | HcpTerraformVariableSetTarget
QueryFunc = Callable[[str], dict[str, Any]]
CommandRunner = Callable[
    [Sequence[str], str | None, Mapping[str, str] | None],
    str,
]


class SlackWebhookSyncCommand:
    def __init__(
        self,
        workspace: str,
        query_func: QueryFunc,
        vault_address: str,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self._workspace = workspace
        self._query_func = query_func
        self._vault_address = vault_address
        self._command_runner = command_runner or self._run_command

    def execute(self, dump_file: Path, dry_run: bool = True) -> None:
        inventory = self._fetch_inventory()
        webhooks = self._parse_dump(dump_file)

        missing = sorted(set(inventory) - set(webhooks))
        if missing:
            raise SlackWebhookSyncError(
                "dump file is missing configured channels: " + ", ".join(missing)
            )

        vault_updates = self._collect_vault_updates(inventory, webhooks)
        hcp_updates = self._collect_hcp_updates(inventory, webhooks)

        vault_changes: dict[str, VaultChange] = {}
        for path, fields in sorted(vault_updates.items()):
            if change := self._vault_changes(path, fields):
                vault_changes[path] = change

        if dry_run:
            self._print_dry_run(vault_updates, vault_changes, hcp_updates)
            return

        for path, change in sorted(vault_changes.items()):
            self._sync_vault_secret(path, change)

        for update in hcp_updates:
            self._sync_hcp_terraform_target(update)

    def _fetch_inventory(self) -> dict[str, tuple[Target, ...]]:
        workspaces = get_slack_webhooks(query_func=self._query_func)
        workspace = next((w for w in workspaces if w.name == self._workspace), None)

        if workspace is None:
            raise SlackWebhookSyncError(f"Slack workspace not found: {self._workspace}")

        inventory: dict[str, tuple[Target, ...]] = {}
        for webhook in workspace.incoming_webhooks or []:
            channel = webhook.channel
            if not channel:
                raise SlackWebhookSyncError("incoming webhook has no channel")
            if channel in inventory:
                raise SlackWebhookSyncError(
                    f"duplicate incoming webhook channel in inventory: {channel}"
                )

            targets = tuple(self._parse_target(target) for target in webhook.targets)
            if not self._has_vault_target(targets):
                raise SlackWebhookSyncError(
                    f"incoming webhook has no Vault target: {channel}"
                )
            inventory[channel] = targets

        return inventory

    def _collect_vault_updates(
        self,
        inventory: dict[str, tuple[Target, ...]],
        webhooks: dict[str, str],
    ) -> dict[str, dict[str, str]]:
        updates: dict[str, dict[str, str]] = {}
        for channel, targets in inventory.items():
            url = webhooks[channel]
            for target in targets:
                if isinstance(target, VaultTarget):
                    fields = updates.setdefault(target.path, {})
                    if target.field in fields and fields[target.field] != url:
                        raise SlackWebhookSyncError(
                            f"vault target has conflicting webhook URLs: "
                            f"{target.path}/{target.field}"
                        )
                    fields[target.field] = url
        return updates

    @staticmethod
    def _has_vault_target(targets: tuple[Target, ...]) -> bool:
        return any(isinstance(target, VaultTarget) for target in targets)

    def _collect_hcp_updates(
        self,
        inventory: dict[str, tuple[Target, ...]],
        webhooks: dict[str, str],
    ) -> tuple[HcpTerraformVariableSetUpdate, ...]:
        updates: dict[HcpTerraformVariableSetTarget, HcpTerraformVariableSetUpdate] = {}
        for channel, targets in inventory.items():
            url = webhooks[channel]
            for target in targets:
                if not isinstance(target, HcpTerraformVariableSetTarget):
                    continue

                existing = updates.get(target)
                if existing is not None and existing.url != url:
                    raise SlackWebhookSyncError(
                        f"HCP variable set target has conflicting webhook URLs: "
                        f"{target}"
                    )
                if existing is None:
                    updates[target] = HcpTerraformVariableSetUpdate(
                        channel=channel,
                        target=target,
                        url=url,
                        change=self._hcp_terraform_change(target),
                    )

        return tuple(
            sorted(
                updates.values(),
                key=lambda update: (update.channel, str(update.target)),
            )
        )

    def _print_dry_run(
        self,
        vault_updates: dict[str, dict[str, str]],
        vault_changes: dict[str, VaultChange],
        hcp_updates: tuple[HcpTerraformVariableSetUpdate, ...],
    ) -> None:
        for path, fields in sorted(vault_updates.items()):
            change = vault_changes.get(path)
            if change is None:
                print(
                    f"[dry-run] unchanged vault-secret {path}: "
                    f"{', '.join(sorted(fields))}"
                )
            else:
                print(
                    f"[dry-run] would update vault-secret {path}: "
                    f"{', '.join(sorted(change.changed))}"
                )

        for update in hcp_updates:
            action = "create" if update.change.method == "POST" else "update"
            print(
                f"[dry-run] would {action} {update.channel}: {update.target} "
                f"({update.change.method} {update.change.path})"
            )

    @staticmethod
    def _parse_target(target: SlackWorkspaceIncomingWebhookTargetV1) -> Target:
        match target.q_type:
            case "vault-secret":
                path = target.path
                field = target.field
                if not path or not field:
                    raise SlackWebhookSyncError(
                        "vault-secret target needs path and field"
                    )
                return VaultTarget(path=path, field=field)
            case "hcp-terraform-variable-set":
                project = target.project
                name = target.name
                variable = target.variable
                if not project or not name or not variable:
                    raise SlackWebhookSyncError(
                        "hcp-terraform-variable-set target needs "
                        "project, name, and variable"
                    )
                return HcpTerraformVariableSetTarget(
                    project=project, name=name, variable=variable
                )
            case target_type:
                raise SlackWebhookSyncError(
                    f"unsupported webhook target type: {target_type}"
                )

    @staticmethod
    def _parse_dump(dump_file: Path) -> dict[str, str]:
        try:
            payload = json.loads(dump_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise SlackWebhookSyncError(f"could not read dump file: {dump_file}") from e

        if not isinstance(payload, dict):
            raise SlackWebhookSyncError("dump file must contain a JSON object")
        if not all(
            isinstance(channel, str) and isinstance(url, str)
            for channel, url in payload.items()
        ):
            raise SlackWebhookSyncError("dump file entries must be strings")

        return cast("dict[str, str]", payload)

    def _sync_vault_secret(self, path: str, change: VaultChange) -> None:
        if change.state.version == 1:
            data = {**change.state.data, **change.changed}
            args = ["vault", "kv", "put", path]
        else:
            data = change.changed
            args = ["vault", "kv", "patch", path]

        self._command_runner(
            [*args, *(f"{field}={url}" for field, url in data.items())],
            None,
            self._vault_environment(),
        )
        print(f"synced vault-secret {path}: {', '.join(sorted(change.changed))}")

    def _vault_changes(self, path: str, fields: dict[str, str]) -> VaultChange | None:
        state = self._read_vault_secret(path)
        changed = {
            field: url for field, url in fields.items() if state.data.get(field) != url
        }
        if not changed:
            return None
        return VaultChange(changed=changed, state=state)

    def _read_vault_secret(self, path: str) -> VaultSecretState:
        output = self._command_runner(
            ["vault", "kv", "get", "-format=json", path],
            None,
            self._vault_environment(),
        )
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as e:
            raise SlackWebhookSyncError("vault returned invalid JSON") from e

        data = payload.get("data")
        if not isinstance(data, dict):
            raise SlackWebhookSyncError(f"vault secret has invalid data: {path}")

        if isinstance(data.get("data"), dict) and isinstance(
            data.get("metadata"), dict
        ):
            return VaultSecretState(data=data["data"], version=2)
        return VaultSecretState(data=data, version=1)

    def _sync_hcp_terraform_target(self, update: HcpTerraformVariableSetUpdate) -> None:
        body = self._hcp_terraform_body(update.target, update.url, update.change)
        self._command_runner(
            [
                "tfctl",
                "api",
                update.change.path,
                "-X",
                update.change.method,
                "-i",
                "-",
            ],
            body,
            None,
        )
        print(f"synced {update.channel}: {update.target}")

    def _hcp_terraform_change(
        self, target: HcpTerraformVariableSetTarget
    ) -> HcpTerraformVariableSetChange:
        project_id = self._hcp_project_id(target.project)
        varset = self._hcp_varset(target, project_id)
        varset_id = varset["id"]
        variable = self._hcp_variable(target, varset_id)

        if variable is None:
            return HcpTerraformVariableSetChange(
                method="POST",
                path=f"/varsets/{varset_id}/relationships/vars",
            )

        return HcpTerraformVariableSetChange(
            method="PATCH",
            path=f"/vars/{variable['id']}",
        )

    @staticmethod
    def _hcp_terraform_body(
        target: HcpTerraformVariableSetTarget,
        url: str,
        change: HcpTerraformVariableSetChange,
    ) -> str:
        if change.method == "POST":
            return json.dumps({
                "data": {
                    "type": "vars",
                    "attributes": {
                        "key": target.variable,
                        "value": url,
                        "category": "terraform",
                        "sensitive": True,
                        "hcl": False,
                    },
                },
            })

        return json.dumps({
            "data": {
                "id": change.path.removeprefix("/vars/"),
                "type": "vars",
                "attributes": {"value": url},
            },
        })

    def _hcp_project_id(self, project: str) -> str:
        data = self._tfctl([
            "/projects/{project}",  # ruff: ignore[missing-f-string-syntax]
            "-p",
            f"project={project}",
        ])
        item = data.get("data") or {}
        project_id = item.get("id")
        if not project_id:
            raise SlackWebhookSyncError(f"could not resolve HCP project: {project}")
        return project_id

    def _hcp_varset(
        self, target: HcpTerraformVariableSetTarget, project_id: str
    ) -> dict[str, Any]:
        data = self._tfctl(["/organizations/{organization}/varsets", "--all"])
        matches = [
            item
            for item in data.get("data") or []
            if item.get("attributes", {}).get("name") == target.name
        ]
        scoped = [
            item
            for item in matches
            if item.get("relationships", {}).get("parent", {}).get("data", {}).get("id")
            == project_id
        ]

        if len(scoped) != 1:
            raise SlackWebhookSyncError(
                f"expected exactly one project-scoped HCP variable set: {target}"
            )
        if scoped[0].get("attributes", {}).get("global"):
            raise SlackWebhookSyncError(f"refusing global HCP variable set: {target}")
        return scoped[0]

    def _hcp_variable(
        self, target: HcpTerraformVariableSetTarget, varset_id: str
    ) -> dict[str, Any] | None:
        data = self._tfctl([f"/varsets/{varset_id}/relationships/vars", "--all"])
        matches = [
            item
            for item in data.get("data") or []
            if item.get("attributes", {}).get("key") == target.variable
        ]
        if len(matches) > 1:
            raise SlackWebhookSyncError(
                f"HCP variable set has duplicate variable: {target.variable}"
            )
        if not matches:
            return None

        attributes = matches[0].get("attributes", {})
        if (
            attributes.get("category") != "terraform"
            or attributes.get("sensitive") is not True
            or attributes.get("hcl") is True
        ):
            raise SlackWebhookSyncError(
                f"HCP variable has unexpected metadata: {target.variable}"
            )
        return matches[0]

    def _tfctl(self, args: Sequence[str]) -> dict[str, Any]:
        output = self._command_runner(["tfctl", "api", *args, "--json"], None, None)
        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            raise SlackWebhookSyncError("tfctl returned invalid JSON") from e

    def _run_command(
        self,
        args: Sequence[str],
        input_text: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        result = subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            env=self._compute_environment(env),
        )
        if result.returncode:
            stderr = result.stderr.strip()
            detail = f": {stderr}" if stderr else ""
            raise SlackWebhookSyncError(
                f"{args[0]} failed with exit code {result.returncode}{detail}"
            )
        return result.stdout

    def _vault_environment(self) -> Mapping[str, str]:
        return {"VAULT_ADDR": self._vault_address}

    @staticmethod
    def _compute_environment(env: Mapping[str, str] | None) -> Mapping[str, str]:
        environment = os.environ.copy()
        if env is not None:
            environment.update(env)
        return environment
