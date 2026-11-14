#!/usr/bin/env python3
"""Rotate one ERv2 CloudWatch access key through qontract-cli.

The command inspects by default. Execution requires the inspected old key ID,
taints only aws_iam_access_key.this, and requests ERv2 reconciliation. Verification
checks the replacement key and ERv2 output-sync status; check consumer health
separately. Shared selectors are rejected because ERv2 selects one namespace.
Results identify additional active IAM keys for separate review.
The caller owns batching and progress records.
"""

# The same file runs inside the provider image without qontract-reconcile.
# ruff: file-ignore[import-outside-top-level]

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from reconcile.external_resources.model import ExternalResource
    from reconcile.utils.secret_reader import SecretReaderBase
    from tools.cli_commands.erv2 import Erv2Cli


class RotationError(Exception):
    pass


class Selector(BaseModel):
    account: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    identifier: str = Field(pattern=r"^[\w+=,.@-]+$")

    @property
    def key(self) -> str:
        return f"{self.account}/{self.identifier}"


class Target(Selector):
    account_id: str = Field(pattern=r"^\d{12}$")
    region: str


class Backend(BaseModel):
    account_id: str = Field(pattern=r"^\d{12}$")
    bucket: str
    region: str


class Request(Selector):
    dry_run: bool = True
    verify: bool = False
    expected_key_id: str | None = Field(default=None, pattern=r"^AKIA[A-Z0-9]{16}$")


class KeyState(BaseModel):
    key_id: str = Field(pattern=r"^AKIA[A-Z0-9]{16}$")
    user: str
    tainted: bool


class IamKey(BaseModel):
    access_key_id: str = Field(alias="AccessKeyId")
    status: Literal["Active", "Inactive"] = Field(alias="Status")


class IamKeys(BaseModel):
    keys: list[IamKey] = Field(alias="AccessKeyMetadata")


class CallerIdentity(BaseModel):
    account: str = Field(alias="Account")


class TerraformInstance(BaseModel):
    attributes: dict[str, Any]
    index_key: str | int | None = None
    deposed: str | None = None
    status: str | None = None


class TerraformResource(BaseModel):
    mode: str
    type: str
    name: str
    module: str | None = None
    instances: list[TerraformInstance]


class TerraformState(BaseModel):
    resources: list[TerraformResource]


class IamStateAttributes(BaseModel):
    id: str = Field(pattern=r"^AKIA[A-Z0-9]{16}$")
    user: str


class CloudwatchInput(BaseModel):
    identifier: str
    region: str


class Result(Selector):
    status: Literal["would_rotate", "requested", "pending", "replaced", "key_changed"]
    access_key_id: str
    expected_key_id: str | None
    resource_status: str
    tainted: bool
    additional_active_key_ids: list[str] = Field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 2 if self.status in {"pending", "key_changed"} else 0


class RotationRuntime(Protocol):
    def operation(
        self,
        target: Target,
        action: Literal["inspect", "taint"],
        expected_key: str | None = None,
    ) -> KeyState: ...
    def iam_keys(self, target: Target) -> list[IamKey]: ...
    def status(self, target: Target) -> str: ...
    def request(self, target: Target) -> None: ...


def checked(
    command: list[str], *, phase: str, env: dict[str, str] | None = None
) -> str:
    """Never echo credential-bearing subprocess output on failure."""
    result = subprocess.run(
        command, capture_output=True, text=True, env=env, check=False
    )
    if result.returncode:
        raise RotationError(
            f"{phase} failed (exit {result.returncode}); output suppressed"
        )
    return result.stdout


def state_metadata(state: TerraformState, expected_user: str) -> KeyState:
    resources = [
        r
        for r in state.resources
        if r.mode == "managed"
        and r.type == "aws_iam_access_key"
        and r.name == "this"
        and r.module is None
    ]
    if len(resources) != 1 or len(resources[0].instances) != 1:
        raise RotationError(
            "Expected exactly one root aws_iam_access_key.this instance"
        )
    instance = resources[0].instances[0]
    attributes = IamStateAttributes.model_validate(instance.attributes)
    if (
        instance.index_key is not None
        or instance.deposed
        or attributes.user != expected_user
    ):
        raise RotationError("Unexpected access-key instance or IAM user")
    return KeyState(
        key_id=attributes.id, user=attributes.user, tainted=instance.status == "tainted"
    )


def container_operation(
    action: str, expected_user: str, expected_key: str | None
) -> KeyState:
    """Runs inside the ERv2 image, with state and credentials confined to the container."""
    if action not in {"inspect", "taint"}:
        raise RotationError("Unknown container operation")
    work = Path(os.environ["TERRAFORM_MODULE_WORK_DIR"])
    shutil.copytree(os.environ.get("TERRAFORM_MODULE_SRC_DIR", "module"), work)
    checked(["generate-tf-config"], phase="Module configuration")
    terraform = ["terraform", f"-chdir={work}"]
    checked(
        terraform + ["init", "-input=false", "-no-color"],
        phase="Terraform initialization",
    )

    def inspect() -> KeyState:
        state = TerraformState.model_validate_json(
            checked(terraform + ["state", "pull"], phase="Remote state read")
        )
        return state_metadata(state, expected_user)

    before = inspect()
    if action == "taint":
        if before.key_id != expected_key or before.tainted:
            raise RotationError(
                "Remote key changed or is already tainted; no mutation attempted"
            )
        checked(
            terraform + ["taint", "-lock-timeout=60s", "aws_iam_access_key.this"],
            phase="Access-key taint",
        )
        after = inspect()
        if after.key_id != expected_key or not after.tainted:
            raise RotationError(
                "State changed during taint; inspect manually before continuing"
            )
        return after
    return before


class Runtime:
    def __init__(
        self,
        target: Target,
        backend: Backend,
        secret_reader: SecretReaderBase,
        client: Erv2Cli,
    ) -> None:
        self.previous_logging_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        self.reader = secret_reader
        self.backend = backend
        self.temporary = tempfile.TemporaryDirectory(
            dir=Path.home(), prefix="cw-key-rotation."
        )
        self.directory = Path(self.temporary.name)
        self.credentials: dict[str, tuple[Path, str]] = {}
        self.images: dict[str, str] = {}
        self.clients: dict[str, Erv2Cli] = {target.key: client}

    def close(self) -> None:
        self.temporary.cleanup()
        logging.disable(self.previous_logging_disable)

    def aws(
        self, credentials: Path, profile: str, region: str, arguments: list[str]
    ) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
        configuration = self.directory / "aws-config"
        configuration.touch(mode=0o600, exist_ok=True)
        env.update(
            AWS_SHARED_CREDENTIALS_FILE=str(credentials),
            AWS_CONFIG_FILE=str(configuration),
            AWS_PROFILE=profile,
            AWS_DEFAULT_REGION=region,
            AWS_EC2_METADATA_DISABLED="true",
            AWS_PAGER="",
        )
        return checked(
            ["aws", *arguments, "--output", "json"],
            phase="AWS " + " ".join(arguments[:2]),
            env=env,
        )

    def client(self, target: Target) -> Erv2Cli:
        from tools.cli_commands.erv2 import Erv2Cli

        if target.key not in self.clients:
            self.clients[target.key] = Erv2Cli(
                provision_provider="aws",
                provisioner=target.account,
                provider="cloudwatch",
                identifier=target.identifier,
                secret_reader=self.reader,
            )
        return self.clients[target.key]

    def prepare(self, target: Target) -> tuple[Erv2Cli, ExternalResource, Path]:
        from reconcile.external_resources.model import (
            ExternalResource,
            TerraformModuleProvisionData,
        )
        from tools.qontract_cli import _get_external_resources_credentials

        client = self.client(target)
        data = ExternalResource.model_validate_json(client.input_data)
        provision = data.provision
        cloudwatch = CloudwatchInput.model_validate(data.data)
        if (
            provision.provision_provider,
            provision.provisioner,
            provision.provider,
            provision.identifier,
            cloudwatch.identifier,
            cloudwatch.region,
        ) != (
            "aws",
            target.account,
            "cloudwatch",
            target.identifier,
            target.identifier,
            target.region,
        ):
            raise RotationError("Live ERv2 input differs from the manifest identity")
        backend = provision.module_provision_data
        expected_key = (
            f"aws/{target.account}/cloudwatch/{target.identifier}/terraform.tfstate"
        )
        if (
            not isinstance(backend, TerraformModuleProvisionData)
            or backend.tf_state_bucket != self.backend.bucket
            or backend.tf_state_region != self.backend.region
            or backend.tf_state_key != expected_key
        ):
            raise RotationError("Live ERv2 backend differs from the manifest")
        if target.account not in self.credentials:
            path = self.directory / (target.account + ".credentials")
            material = _get_external_resources_credentials(self.reader, target.account)
            with path.open("x", encoding="utf-8") as stream:
                os.chmod(path, 0o600)
                stream.write(material)
            for profile, expected_id in [
                ("default", target.account_id),
                ("external-resources-state", self.backend.account_id),
            ]:
                identity = CallerIdentity.model_validate_json(
                    self.aws(
                        path, profile, target.region, ["sts", "get-caller-identity"]
                    )
                )
                if identity.account != expected_id:
                    raise RotationError(
                        f"AWS identity mismatch for {target.account}/{profile}"
                    )
            self.credentials[target.account] = (path, target.account_id)
        path, account_id = self.credentials[target.account]
        if account_id != target.account_id:
            raise RotationError("Conflicting account IDs in manifest")
        return client, data, path

    def operation(
        self,
        target: Target,
        action: Literal["inspect", "taint"],
        expected_key: str | None = None,
    ) -> KeyState:
        client, data, credentials = self.prepare(target)
        image = client.image
        if image not in self.images:
            checked(["docker", "pull", image], phase="ERv2 image pull")
            self.images[image] = checked(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image],
                phase="ERv2 image resolution",
            ).strip()
        input_path = self.directory / "input.json"
        input_path.write_text(data.model_dump_json())
        os.chmod(input_path, 0o600)
        command = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python3",
            "-v",
            f"{input_path}:/inputs/input.json:ro",
            "-v",
            f"{credentials}:/credentials:ro",
            "-v",
            f"{Path(__file__).resolve()}:/rotation.py:ro",
        ]
        for value in [
            "AWS_SHARED_CREDENTIALS_FILE=/credentials",
            "AWS_CONFIG_FILE=/dev/null",
            "AWS_PROFILE=default",
            "AWS_EC2_METADATA_DISABLED=true",
            "TERRAFORM_MODULE_WORK_DIR=/tmp/cw-rotation",
            "BACKEND_TF_FILE=/tmp/cw-rotation/backend.tf",
            "TF_VARS_FILE=/tmp/cw-rotation/terraform.tfvars.json",
            "LOCAL_STATE=False",
            "TF_IN_AUTOMATION=true",
        ]:
            command.extend(["-e", value])
        command.extend([
            self.images[image],
            "/rotation.py",
            "_container",
            action,
            target.identifier,
        ])
        if expected_key is not None:
            command.append(expected_key)
        return KeyState.model_validate_json(
            checked(command, phase="ERv2 state " + action)
        )

    def iam_keys(self, target: Target) -> list[IamKey]:
        _, _, credentials = self.prepare(target)
        return IamKeys.model_validate_json(
            self.aws(
                credentials,
                "default",
                target.region,
                ["iam", "list-access-keys", "--user-name", target.identifier],
            )
        ).keys

    def status(self, target: Target) -> str:
        from reconcile.external_resources.integration import get_aws_api
        from reconcile.external_resources.model import ExternalResourceKey
        from reconcile.external_resources.state import ExternalResourcesStateDynamoDB
        from reconcile.typed_queries.external_resources import get_settings
        from reconcile.utils import gql

        settings = get_settings()
        with get_aws_api(
            query_func=gql.get_api().query,
            account_name=settings.state_dynamodb_account.name,
            region=settings.state_dynamodb_region,
            secret_reader=self.reader,
        ) as api:
            manager = ExternalResourcesStateDynamoDB(
                aws_api=api,
                table_name=settings.state_dynamodb_table,
                load_partial_resources=False,
            )
            key = ExternalResourceKey(
                provision_provider="aws",
                provisioner_name=target.account,
                provider="cloudwatch",
                identifier=target.identifier,
            )
            return manager.get_external_resource_state(key).resource_status.value

    def request(self, target: Target) -> None:
        self.client(target).reconcile()
        if self.status(target) not in {
            "RECONCILIATION_REQUESTED",
            "IN_PROGRESS",
            "PENDING_SECRET_SYNC",
            "CREATED",
        }:
            raise RotationError(
                "Reconciliation request did not reach an expected ERv2 status"
            )


def validate_request(request: Request) -> None:
    if request.verify and not request.dry_run:
        raise RotationError("--verify is read-only; keep --dry-run enabled")
    if (request.verify or not request.dry_run) and request.expected_key_id is None:
        raise RotationError(
            "Supply --expected-key-id from inspection before execution or verification"
        )


def rotate(request: Request, target: Target, runtime: RotationRuntime) -> Result:
    validate_request(request)
    if (request.account, request.identifier) != (target.account, target.identifier):
        raise RotationError("Resolved target differs from requested resource")
    state = runtime.operation(target, "inspect")
    keys = runtime.iam_keys(target)
    status = runtime.status(target)
    if status in {"ERROR", "NOT_EXISTS", "DELETED", "ABANDONED", "DELETE_IN_PROGRESS"}:
        raise RotationError(f"ERv2 status is {status}; investigate before rotation")

    def result(
        value: Literal[
            "would_rotate", "requested", "pending", "replaced", "key_changed"
        ],
    ) -> Result:
        return Result(
            account=target.account,
            identifier=target.identifier,
            status=value,
            access_key_id=state.key_id,
            expected_key_id=request.expected_key_id,
            resource_status=status,
            tainted=state.tainted,
            additional_active_key_ids=sorted(
                key.access_key_id
                for key in keys
                if key.status == "Active" and key.access_key_id != state.key_id
            ),
        )

    active = any(k.access_key_id == state.key_id and k.status == "Active" for k in keys)
    if request.verify:
        old_present = any(k.access_key_id == request.expected_key_id for k in keys)
        complete = (
            state.key_id != request.expected_key_id
            and not old_present
            and active
            and not state.tainted
            and status == "CREATED"
        )
        return result("replaced" if complete else "pending")
    if request.expected_key_id is not None and state.key_id != request.expected_key_id:
        return result("key_changed")
    if status != "CREATED":
        return result("pending")
    if not active:
        raise RotationError("Terraform key is not active on the expected IAM user")
    if request.dry_run:
        return result("would_rotate")
    if not state.tainted:
        runtime.operation(target, "taint", request.expected_key_id)
    runtime.request(target)
    state.tainted = True
    status = "RECONCILIATION_REQUESTED"
    return result("requested")


def account_id(name: str) -> str:
    from reconcile.gql_definitions.external_resources.aws_account_identities import (
        query,
    )
    from reconcile.utils import gql

    accounts = (
        query(gql.get_api().query, variables={"filter": {"name": name}}).accounts or []
    )
    if len(accounts) != 1 or accounts[0].name != name:
        raise RotationError(f"Expected exactly one AWS account named {name}")
    return accounts[0].uid


def run_single(
    provisioner: str,
    identifier: str,
    secret_reader: SecretReaderBase,
    *,
    dry_run: bool = True,
    expected_key_id: str | None = None,
    verify: bool = False,
) -> Result:
    from reconcile.external_resources.model import ExternalResource
    from reconcile.typed_queries.external_resources import get_settings
    from tools.cli_commands.erv2 import Erv2Cli

    request = Request(
        account=provisioner,
        identifier=identifier,
        dry_run=dry_run,
        expected_key_id=expected_key_id,
        verify=verify,
    )
    validate_request(request)
    client = Erv2Cli(
        provision_provider="aws",
        provisioner=provisioner,
        provider="cloudwatch",
        identifier=identifier,
        secret_reader=secret_reader,
    )
    if client.resource_bindings_count != 1:
        raise RotationError(
            "CloudWatch rotation requires exactly one namespace binding; "
            "shared selectors need explicit consumer synchronization"
        )
    data = ExternalResource.model_validate_json(client.input_data)
    cloudwatch = CloudwatchInput.model_validate(data.data)
    settings = get_settings()
    target = Target(
        account=provisioner,
        account_id=account_id(provisioner),
        identifier=identifier,
        region=cloudwatch.region,
    )
    backend = Backend(
        account_id=account_id(settings.state_dynamodb_account.name),
        bucket=settings.tf_state_bucket,
        region=settings.tf_state_region,
    )
    runtime = Runtime(target, backend, secret_reader, client)
    try:
        return rotate(request, target, runtime)
    finally:
        runtime.close()


def error_message(error: Exception) -> str:
    # Credential-library errors can contain sensitive input.
    return (
        str(error)
        if isinstance(error, RotationError)
        else f"{type(error).__name__}; details suppressed to protect credentials"
    )


def main() -> None:
    """Private entry point mounted inside the ERv2 provider container."""
    try:
        if len(sys.argv) not in {4, 5} or sys.argv[1] != "_container":
            raise RotationError(
                "Use qontract-cli external-resources ... rotate-access-key"
            )
        os.umask(0o077)
        expected_key = sys.argv[4] if len(sys.argv) == 5 else None
        print(
            container_operation(
                sys.argv[2], sys.argv[3], expected_key
            ).model_dump_json()
        )
    except Exception as error:
        print(f"ERROR: {error_message(error)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
