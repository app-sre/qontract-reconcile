from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from difflib import get_close_matches
from enum import Enum
from pathlib import Path
from subprocess import CalledProcessError, run
from typing import Any, Protocol

from pydantic import BaseModel
from rich import print as rich_print
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm, IntPrompt

from reconcile.external_resources.integration import get_aws_api
from reconcile.external_resources.manager import setup_factories
from reconcile.external_resources.meta import FLAG_RESOURCE_MANAGED_BY_ERV2
from reconcile.external_resources.model import (
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    ExternalResourcesInventory,
    load_module_inventory,
)
from reconcile.external_resources.state import (
    ExternalResourcesStateDynamoDB,
    ResourceStatus,
)
from reconcile.typed_queries.external_resources import (
    get_modules,
    get_namespaces,
    get_settings,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.secret_reader import SecretReaderBase


def progress_spinner() -> Progress:
    """Display shiny progress spinner."""
    console = Console(record=True)
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    )


@contextmanager
def pause_progress_spinner(progress: Progress | None) -> Iterator:
    """Pause the progress spinner."""
    if progress:
        progress.stop()
        UP = "\x1b[1A"
        CLEAR = "\x1b[2K"
        for task in progress.tasks:
            if task.finished:
                continue
            print(UP + CLEAR + UP)
    yield
    if progress:
        progress.start()


@contextmanager
def task(progress: Progress | None, description: str) -> Iterator:
    """Display a task in the progress spinner."""
    if progress:
        task = progress.add_task(description, total=1)
    yield
    if progress:
        progress.advance(task)


class Erv2Cli:
    def __init__(
        self,
        provision_provider: str,
        provisioner: str,
        provider: str,
        identifier: str,
        secret_reader: SecretReaderBase,
        temp_dir: Path | None = None,
        progress_spinner: Progress | None = None,
    ) -> None:
        self._provision_provider = provision_provider
        self._provisioner = provisioner
        self._provider = provider
        self._identifier = identifier
        self._temp_dir = temp_dir
        self.progress_spinner = progress_spinner

        namespaces = [ns for ns in get_namespaces() if ns.external_resources]
        er_inventory = ExternalResourcesInventory(namespaces)

        try:
            spec = er_inventory.get_inventory_spec(
                provision_provider=provision_provider,
                provisioner=provisioner,
                provider=provider,
                identifier=identifier,
            )
        except FetchResourceError:
            rich_print(
                f"[b red]Resource {provision_provider}/{provisioner}/{provider}/{identifier} not found[/]. Ensure `managed_by_erv2: true` is set!"
            )
            sys.exit(1)

        self._secret_reader = secret_reader
        self._er_settings = get_settings()
        m_inventory = load_module_inventory(get_modules())
        factories = setup_factories(
            self._er_settings, m_inventory, er_inventory, self._secret_reader
        )
        f = factories.get_factory(spec.provision_provider)
        self._module_configuration = (
            ExternalResourceModuleConfiguration.resolve_configuration(
                m_inventory.get_from_spec(spec), spec, self._er_settings
            )
        )
        self._resource = f.create_external_resource(spec, self._module_configuration)
        f.validate_external_resource(self._resource, self._module_configuration)

    @property
    def input_data(self) -> str:
        return self._resource.json(exclude={"data": {FLAG_RESOURCE_MANAGED_BY_ERV2}})

    @property
    def image(self) -> str:
        return self._module_configuration.image_version

    @property
    def temp(self) -> Path:
        if not self._temp_dir:
            raise ValueError("Temp directory is not set!")
        return self._temp_dir

    def reconcile(self) -> None:
        with get_aws_api(
            query_func=gql.get_api().query,
            account_name=self._er_settings.state_dynamodb_account.name,
            region=self._er_settings.state_dynamodb_region,
            secret_reader=self._secret_reader,
        ) as aws_api:
            state_manager = ExternalResourcesStateDynamoDB(
                aws_api=aws_api,
                table_name=self._er_settings.state_dynamodb_table,
            )
            key = ExternalResourceKey(
                provision_provider=self._provision_provider,
                provisioner_name=self._provisioner,
                provider=self._provider,
                identifier=self._identifier,
            )
            current_state = state_manager.get_external_resource_state(key)
            if current_state.resource_status != ResourceStatus.NOT_EXISTS:
                state_manager.update_resource_status(
                    key, ResourceStatus.RECONCILIATION_REQUESTED
                )
            else:
                rich_print("[b red]External Resource does not exist")

    def build_cdktf(self, credentials: Path) -> None:
        """Run the CDKTF container and return the generated CDKTF json."""
        input_file = self.temp / "input.json"
        input_file.write_text(self.input_data)

        # delete previous ERv2 container
        run(["docker", "rm", "-f", "erv2"], capture_output=True, check=True)

        try:
            cdktf_outdir = "/tmp/cdktf.out"

            # run cdktf synth
            with task(self.progress_spinner, "-- Running CDKTF synth"):
                run(["docker", "pull", self.image], check=True, capture_output=True)
                run(
                    [
                        "docker",
                        "run",
                        "--name",
                        "erv2",
                        "-v",
                        f"{input_file!s}:/inputs/input.json:Z",
                        "-v",
                        f"{credentials!s}:/credentials:Z",
                        "-e",
                        "AWS_SHARED_CREDENTIALS_FILE=/credentials",
                        "--entrypoint",
                        "cdktf",
                        self.image,
                        "synth",
                        "--output",
                        cdktf_outdir,
                    ],
                    check=True,
                    capture_output=True,
                )

            # # get the cdk.tf.json
            with task(self.progress_spinner, "-- Copying the generated cdk.tf.json"):
                run(
                    [
                        "docker",
                        "cp",
                        f"erv2:{cdktf_outdir}/stacks/CDKTF/cdk.tf.json",
                        str(self.temp),
                    ],
                    check=True,
                    capture_output=True,
                )
        except CalledProcessError as e:
            if e.stderr:
                print(e.stderr.decode("utf-8"))
            if e.stdout:
                print(e.stdout.decode("utf-8"))
            raise

    def enter_shell(self, credentials: Path) -> None:
        """Run the ERv2 container and enter the shell."""
        input_file = self.temp / "input.json"
        input_file.write_text(self.input_data)

        try:
            run(["docker", "pull", self.image], check=True, capture_output=True)
            run(
                [
                    "docker",
                    "run",
                    "--name",
                    "erv2-debug-shell",
                    "--rm",
                    "-it",
                    "-v",
                    f"{input_file!s}:/inputs/input.json:Z",
                    "-v",
                    f"{credentials!s}:/credentials:Z",
                    "-e",
                    "AWS_SHARED_CREDENTIALS_FILE=/credentials",
                    "-e",
                    "WORK=/tmp/work",
                    "--entrypoint",
                    "/bin/bash",
                    self.image,
                ],
                check=True,
            )
        except CalledProcessError as e:
            if e.stderr:
                print(e.stderr.decode("utf-8"))
            if e.stdout:
                print(e.stdout.decode("utf-8"))
            raise

    def force_unlock(self, credentials: Path, lock_id: str) -> None:
        """Run 'terraform force-unlock' in a CDKTF container."""
        input_file = self.temp / "input.json"
        input_file.write_text(self.input_data)

        try:
            run(["docker", "pull", self.image], check=True, capture_output=True)
            run(
                [
                    "docker",
                    "run",
                    "-e",
                    "TERRAFORM_MODULE_WORK_DIR=/tmp/migration",
                    "-e",
                    "BACKEND_TF_FILE=/tmp/migration/backend.tf",
                    "-e",
                    "TF_VARS_FILE=/tmp/migration/terraform.tfvars.json",
                    "--name",
                    "erv2-unlock",
                    "--rm",
                    "-v",
                    f"{input_file!s}:/inputs/input.json:Z",
                    "-v",
                    f"{credentials!s}:/credentials:Z",
                    "-e",
                    "AWS_SHARED_CREDENTIALS_FILE=/credentials",
                    "--entrypoint",
                    "/bin/bash",
                    self.image,
                    "-c",
                    "mkdir -p $TERRAFORM_MODULE_WORK_DIR;"
                    "cp -rf module/* $TERRAFORM_MODULE_WORK_DIR;"
                    "generate-tf-config && "
                    "terraform -chdir=$TERRAFORM_MODULE_WORK_DIR init && "
                    f"terraform -chdir=$TERRAFORM_MODULE_WORK_DIR force-unlock -force '{lock_id}'",
                ],
                check=True,
            )
        except CalledProcessError as e:
            if e.stderr:
                print(e.stderr.decode("utf-8"))
            if e.stdout:
                print(e.stdout.decode("utf-8"))
            raise


class TfRun(Protocol):
    def __call__(self, path: Path, cmd: list[str]) -> str: ...


def tf_run(path: Path, cmd: list[str]) -> str:
    env = os.environ.copy()
    env["TF_CLI_ARGS"] = "-no-color"
    try:
        return run(
            ["terraform", *cmd],
            cwd=path,
            check=True,
            capture_output=True,
            env=env,
        ).stdout.decode("utf-8")
    except CalledProcessError as e:
        if e.stderr:
            print(e.stderr.decode("utf-8"))
        if e.stdout:
            print(e.stdout.decode("utf-8"))
        raise


class TfAction(Enum):
    CREATE = "create"
    DESTROY = "delete"


class Change(BaseModel):
    before: Any | None = None
    after: Any | None = None


class TfResource(BaseModel):
    address: str
    change: Change | None = None

    @property
    def id(self) -> str:
        return self.address.split(".")[1]

    @property
    def type(self) -> str:
        return self.address.split(".")[0]

    def __str__(self) -> str:
        return self.address

    def __repr__(self) -> str:
        return str(self)


class TfResourceList(BaseModel):
    resources: list[TfResource]

    def __iter__(self) -> Iterator[TfResource]:  # type: ignore
        return iter(self.resources)

    def get_resource_by_address(self, address: str) -> TfResource | None:
        for resource in self.resources:
            if resource.address == address:
                return resource
        return None

    def get_resource_by_type(self, type: str) -> TfResource:
        results = self.get_resources_by_type(type)
        if len(results) > 1:
            raise ValueError(f"More than one resource found for type '{type}'!")
        return results[0]

    def get_resources_by_type(self, type: str) -> list[TfResource]:
        results = [resource for resource in self.resources if resource.type == type]
        if not results:
            raise KeyError(f"Resource type '{type}' not found!")
        return results

    def __getitem__(self, tf_resource: TfResource) -> list[TfResource]:
        """Get a resource by searching the resource list.

        self holds the source resources (terraform-resources).
        The tf_resource is the destination resource (ERv2).
        """
        if resource := self.get_resource_by_address(tf_resource.address):
            # exact match by AWS address
            return [resource]

        # a resource with the same ID does not exist
        # let's try to find the resource by the AWS type
        results = self.get_resources_by_type(tf_resource.type)
        if len(results) == 1:
            # there is just one resource with the same type
            # this must be the searched resource.
            return results

        # ok, now it's getting tricky. Let's use difflib and let the user decide.
        possible_matches_ids = get_close_matches(
            tf_resource.id, [r.id for r in results]
        )
        return [r for r in results if r.id in possible_matches_ids]

    def __len__(self) -> int:
        return len(self.resources)


class TerraformCli:
    def __init__(
        self,
        path: Path,
        dry_run: bool = True,
        tf_run: TfRun = tf_run,
        progress_spinner: Progress | None = None,
    ) -> None:
        self._path = path
        self._dry_run = dry_run
        self._tf_run = tf_run
        self.progress_spinner = progress_spinner
        self.initialized = False

    def init(self) -> None:
        """Initialize the terraform modules."""
        self._tf_init()
        self._tf_plan()
        self._tf_state_pull()
        self.initialized = True

    @property
    def state_file(self) -> Path:
        return self._path / "state.json"

    def _tf_init(self) -> None:
        with task(self.progress_spinner, "-- Running terraform init"):
            self._tf_run(self._path, ["init"])

    def _tf_plan(self) -> None:
        with task(self.progress_spinner, "-- Running terraform plan"):
            self._tf_run(self._path, ["plan", "-out=plan.out"])

    def _tf_state_pull(self) -> None:
        with task(self.progress_spinner, "-- Retrieving the terraform state"):
            self.state_file.write_text(self._tf_run(self._path, ["state", "pull"]))

    def _tf_state_push(self) -> None:
        with task(
            self.progress_spinner,
            f"-- Uploading the terraform state {'[b red](DRY-RUN)' if self._dry_run else ''}",
        ):
            if not self._dry_run:
                self._tf_run(self._path, ["state", "push", str(self.state_file)])

    def _tf_import(self, address: str, value: str) -> None:
        """Import a resource.

        !!! Attention !!!

        Because terraform import doesn't use the local state file and always imports the resource to the remote state,
        we need to push and pull the state file again.
        """
        # push local changes
        self._tf_state_push()
        with task(
            self.progress_spinner,
            f"-- Importing resource {address} {'[b red](DRY-RUN)' if self._dry_run else ''}",
        ):
            if not self._dry_run:
                self._tf_run(self._path, ["import", address, value])
        # and pull the state file again
        self._tf_state_pull()

    def upload_state(self) -> None:
        self._tf_state_push()

    def resource_changes(self, action: TfAction) -> TfResourceList:
        """Get the resource changes."""
        plan = json.loads(self._tf_run(self._path, ["show", "-json", "plan.out"]))
        return TfResourceList(
            resources=[
                TfResource(
                    address=r["address"],
                    change=Change(**r["change"]),
                )
                for r in plan["resource_changes"]
                if action.value.lower() in r["change"]["actions"]
            ]
        )

    def move_resource(
        self, source_state_file: Path, source: TfResource, destination: TfResource
    ) -> None:
        """Move the resource from source state file to destination state file."""
        with task(
            self.progress_spinner,
            f"-- Moving {destination} {'[b red](DRY-RUN)' if self._dry_run else ''}",
        ):
            if not self._dry_run:
                self._tf_run(
                    self._path,
                    [
                        "state",
                        "mv",
                        "-lock=false",
                        f"-state={source_state_file!s}",
                        f"-state-out={self.state_file!s}",
                        f"{source.address}",
                        f"{destination.address}",
                    ],
                )

    def commit(self, source: TerraformCli) -> None:
        """Commit the changes."""
        if not self._dry_run:
            if self.progress_spinner:
                self.progress_spinner.stop()
            if not Confirm.ask(
                "\nEverything ok? Would you like to upload the modified terraform states",
                default=True,
            ):
                return

            if self.progress_spinner:
                self.progress_spinner.start()

            # finally push the terraform states
            self.upload_state()
            source.upload_state()

    def _elasticache_import_password(
        self, destination: TfResource, password: str
    ) -> None:
        """Import the elasticache auth_token random_password."""
        self._tf_import(address=destination.address, value=password)

        if (
            not destination.change
            or not destination.change.after
            or not destination.change.after.get("override_special")
        ):
            # nothing to change, nothing to do
            return

        state_data = json.loads(self.state_file.read_text())
        state_data["serial"] += 1
        if self._dry_run:
            # in dry-run mode, tf_import is a no-op, therefore, the password is not in the state yet.
            return
        state_password_obj = next(
            r for r in state_data["resources"] if r["name"] == destination.id
        )

        # Set the "override_special" to disable the password reset
        state_password_obj["instances"][0]["attributes"]["override_special"] = (
            destination.change.after["override_special"]
        )
        # Write the state,
        self.state_file.write_text(json.dumps(state_data, indent=2))

    def migrate_elasticache_resources(self, source: TerraformCli) -> None:
        source_resources = source.resource_changes(TfAction.DESTROY)
        destination_resources = self.resource_changes(TfAction.CREATE)
        if not source_resources or not destination_resources:
            raise ValueError("No resource changes found!")

        source_ec = source_resources.get_resource_by_type(
            "aws_elasticache_replication_group"
        )
        if not source_ec.change or not source_ec.change.before:
            raise ValueError(
                "Something went wrong with the source elasticache instance!"
            )

        current_auth_token = source_ec.change.before.get("auth_token")
        if current_auth_token:
            with suppress(KeyError):
                self._elasticache_import_password(
                    destination_resources.get_resource_by_type("random_password"),
                    current_auth_token,
                )

        # migrate resources
        for destination_resource in destination_resources:
            if current_auth_token and destination_resource.type == "random_password":
                # random password handled above
                continue

            possible_source_resouces = source_resources[destination_resource]
            if not possible_source_resouces or len(possible_source_resouces) > 1:
                raise ValueError(
                    f"Either source resource for {destination_resource} not found or more than one resource found!"
                )
            self.move_resource(
                source_state_file=source.state_file,
                source=possible_source_resouces[0],
                destination=destination_resource,
            )
        self.commit(source)

    def migrate_resources(self, source: TerraformCli) -> None:
        """Migrate the resources from source."""
        # if not self.initialized or not source.initialized:
        #     raise ValueError("Terraform must be initialized before!")

        source_resources = source.resource_changes(TfAction.DESTROY)
        destination_resources = self.resource_changes(TfAction.CREATE)

        if not source_resources or not destination_resources:
            raise ValueError("No resource changes found!")

        if len(source_resources) != len(destination_resources):
            with pause_progress_spinner(self.progress_spinner):
                rich_print(
                    "[b red]The number of changes (ERv2 vs terraform-resource) does not match! Please review them carefully![/]"
                )
                rich_print("ERv2:")
                rich_print(
                    "\n".join([
                        f"  {i}: {r.address}"
                        for i, r in enumerate(destination_resources, start=1)
                    ])
                )
                rich_print("Terraform:")
                rich_print(
                    "\n".join([
                        f"  {i}: {r.address}"
                        for i, r in enumerate(source_resources, start=1)
                    ])
                )
                if not Confirm.ask("Would you like to continue anyway?", default=False):
                    return

        for destination_resource in destination_resources:
            possible_source_resouces = source_resources[destination_resource]
            if not possible_source_resouces:
                raise ValueError(
                    f"Source resource for {destination_resource} not found!"
                )
            elif len(possible_source_resouces) == 1:
                # just one resource found.
                source_resource = possible_source_resouces[0]
            else:
                # more than one resource found. Let the user decide.
                with pause_progress_spinner(self.progress_spinner):
                    rich_print(
                        f"[b red]{destination_resource.address} not found![/] Please select the related source ID manually!"
                    )
                    for i, r in enumerate(possible_source_resouces, start=1):
                        print(f"{i}: {r.address}")

                    index = IntPrompt.ask(
                        ":boom: Enter the number",
                        choices=[
                            str(i) for i in range(1, len(possible_source_resouces) + 1)
                        ],
                        show_choices=False,
                    )
                    source_resource = possible_source_resouces[index - 1]

            self.move_resource(
                source_state_file=source.state_file,
                source=source_resource,
                destination=destination_resource,
            )

        self.commit(source)
