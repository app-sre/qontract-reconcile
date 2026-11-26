from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
class HcpTerraformVariableSetTarget:
    project: str
    name: str
    variable: str

    def __str__(self) -> str:
        return f"hcp-terraform-variable-set {self.project}/{self.name}/{self.variable}"


Target = VaultTarget | HcpTerraformVariableSetTarget
QueryFunc = Callable[[str], dict[str, Any]]
CommandRunner = Callable[[Sequence[str], str | None], str]


class SlackWebhookSyncCommand:
    def __init__(
        self,
        workspace: str,
        query_func: QueryFunc,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self._workspace = workspace
        self._query_func = query_func
        self._command_runner = command_runner or self._run_command

    def execute(self, dump_file: Path, dry_run: bool = True) -> None:
        inventory = self._fetch_inventory()
        webhooks = self._parse_dump(dump_file)

        missing = sorted(set(inventory) - set(webhooks))
        if missing:
            raise SlackWebhookSyncError(
                "dump file is missing configured channels: " + ", ".join(missing)
            )

        for channel in sorted(inventory):
            url = webhooks[channel]
            for target in inventory[channel]:
                if dry_run:
                    print(f"[dry-run] {channel}: {target}")
                    continue

                if isinstance(target, VaultTarget):
                    self._sync_vault_target(target, url)
                else:
                    self._sync_hcp_terraform_target(target, url)
                print(f"synced {channel}: {target}")

    def _fetch_inventory(self) -> dict[str, tuple[Target, ...]]:
        workspaces = get_slack_webhooks(query_func=self._query_func)
        matches = [w for w in workspaces if w.name == self._workspace]

        if len(matches) != 1:
            raise SlackWebhookSyncError(
                f"expected exactly one Slack workspace named {self._workspace}, "
                f"found {len(matches)}"
            )

        inventory: dict[str, tuple[Target, ...]] = {}
        for webhook in matches[0].incoming_webhooks or []:
            channel = webhook.channel
            if not channel:
                raise SlackWebhookSyncError("incoming webhook has no channel")
            if channel in inventory:
                raise SlackWebhookSyncError(
                    f"duplicate incoming webhook channel in inventory: {channel}"
                )

            targets = tuple(self._parse_target(target) for target in webhook.targets)
            if not any(isinstance(target, VaultTarget) for target in targets):
                raise SlackWebhookSyncError(
                    f"incoming webhook has no Vault target: {channel}"
                )
            inventory[channel] = targets

        return inventory

    @staticmethod
    def _parse_target(target: SlackWorkspaceIncomingWebhookTargetV1) -> Target:
        target_type = target.q_type
        if target_type == "vault-secret":
            path = target.path
            field = target.field
            if not path or not field:
                raise SlackWebhookSyncError("vault-secret target needs path and field")
            return VaultTarget(path=path, field=field)

        if target_type == "hcp-terraform-variable-set":
            project = target.project
            name = target.name
            variable = target.variable
            if not project or not name or not variable:
                raise SlackWebhookSyncError(
                    "hcp-terraform-variable-set target needs project, name, and variable"
                )
            return HcpTerraformVariableSetTarget(
                project=project, name=name, variable=variable
            )

        raise SlackWebhookSyncError(f"unsupported webhook target type: {target_type}")

    @staticmethod
    def _parse_dump(dump_file: Path) -> dict[str, str]:
        if dump_file.stat().st_mode & 0o077:
            raise SlackWebhookSyncError(
                f"dump file must not be readable by group or other: {dump_file}"
            )

        try:
            payload = json.loads(dump_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise SlackWebhookSyncError(f"could not read dump file: {dump_file}") from e

        if not isinstance(payload, dict):
            raise SlackWebhookSyncError("dump file must contain a JSON object")

        values: dict[str, str] = {}
        for raw_channel, raw_url in payload.items():
            if not isinstance(raw_channel, str) or not raw_channel.strip():
                raise SlackWebhookSyncError("dump file has an invalid channel key")
            if not isinstance(raw_url, str):
                raise SlackWebhookSyncError(f"dump channel {raw_channel} has no URL")

            channel = raw_channel.strip().removeprefix("#")
            url = raw_url
            if not channel:
                raise SlackWebhookSyncError("dump file has an invalid channel key")
            if not url.startswith("https://"):
                raise SlackWebhookSyncError(
                    f"dump channel {channel} has an invalid URL"
                )

            values[channel] = url

        return values

    def _sync_vault_target(self, target: VaultTarget, url: str) -> None:
        self._command_runner(
            ["vault", "kv", "patch", target.path, f"{target.field}=-"],
            url,
        )

    def _sync_hcp_terraform_target(
        self, target: HcpTerraformVariableSetTarget, url: str
    ) -> None:
        project_id = self._hcp_project_id(target.project)
        varset = self._hcp_varset(target, project_id)
        varset_id = varset["id"]
        variable = self._hcp_variable(target, varset_id)

        if variable is None:
            body = {
                "data": {
                    "type": "vars",
                    "attributes": {
                        "key": target.variable,
                        "value": url,
                        "category": "terraform",
                        "sensitive": True,
                        "hcl": False,
                    },
                }
            }
            path = f"/varsets/{varset_id}/relationships/vars"
            method = "POST"
        else:
            body = {
                "data": {
                    "id": variable["id"],
                    "type": "vars",
                    "attributes": {"value": url},
                }
            }
            path = f"/vars/{variable['id']}"
            method = "PATCH"

        self._command_runner(
            ["tfctl", "api", path, "-X", method, "-i", "-"],
            json.dumps(body),
        )

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
        output = self._command_runner(["tfctl", "api", *args, "--json"], None)
        try:
            return json.loads(output)
        except json.JSONDecodeError as e:
            raise SlackWebhookSyncError("tfctl returned invalid JSON") from e

    @staticmethod
    def _run_command(args: Sequence[str], input_text: str | None = None) -> str:
        result = subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise SlackWebhookSyncError(
                f"{args[0]} failed with exit code {result.returncode}"
            )
        return result.stdout
