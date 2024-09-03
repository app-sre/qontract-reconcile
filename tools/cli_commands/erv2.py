from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from subprocess import CalledProcessError, run
from typing import Protocol

from pydantic import BaseModel
from rich import print as rich_print
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Confirm

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
        temp_dir: Path,
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
        self._resource = f.create_external_resource(spec)
        f.validate_external_resource(self._resource)
        self._module_configuration = (
            ExternalResourceModuleConfiguration.resolve_configuration(
                m_inventory.get_from_spec(spec), spec
            )
        )

    @property
    def input_data(self) -> str:
        return self._resource.json(exclude={"data": {FLAG_RESOURCE_MANAGED_BY_ERV2}})

    @property
    def image(self) -> str:
        return self._module_configuration.image_version

    @property
    def temp(self) -> Path:
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
            # run cdktf synth
            with task(self.progress_spinner, "-- Running CDKTF synth"):
                run(
                    [
                        "docker",
                        "run",
                        "--name",
                        "erv2",
                        "--mount",
                        f"type=bind,source={input_file!s},target=/inputs/input.json",
                        "--mount",
                        f"type=bind,source={credentials!s},target=/credentials",
                        "-e",
                        "DRY_RUN=True",
                        self.image,
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
                        "erv2:/home/app/cdktf.out/stacks/CDKTF/cdk.tf.json",
                        str(self.temp),
                    ],
                    check=True,
                    capture_output=True,
                )
        except CalledProcessError as e:
            print(e.stderr.decode("utf-8"))
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
        print(e.stderr.decode("utf-8"))
        print(e.stdout.decode("utf-8"))
        raise


class TfAction(Enum):
    CREATE = "create"
    DESTROY = "delete"


class TfResource(BaseModel):
    address: str

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

    def __lt__(self, other: TfResource) -> bool:
        return self.address < other.address


class TfResourceList(BaseModel):
    resources: list[TfResource]

    def __iter__(self) -> Iterator[TfResource]:  # type: ignore
        return iter(self.resources)

    def _get_resource_by_address(self, address: str) -> TfResource | None:
        for resource in self.resources:
            if resource.address == address:
                return resource
        return None

    def _get_resources_by_type(self, type: str) -> list[TfResource]:
        results = [resource for resource in self.resources if resource.type == type]
        if not results:
            raise KeyError(f"Resource type {type} not found!")
        return results

    def __getitem__(self, tf_resource: TfResource) -> TfResource:
        """Get a resource by searching the resource list.

        self holds the source resources (terraform-resources).
        The tf_resource is the destination resource (ERv2).
        """
        if resource := self._get_resource_by_address(tf_resource.address):
            # exact match by AWS address
            return resource

        # a resource with the same ID does not exist
        # let's try to find the resource by the AWS type
        results = self._get_resources_by_type(tf_resource.type)
        if len(results) == 1:
            # there is just one resource with the same type
            # this must be the searched resource.
            return results[0]

        # ok, now it's getting tricky:
        # * we found multiple resources with the same AWS type
        # * we need to find the correct resource by the ID
        # * but we know that the ID is slightly different

        # reverse sort to get the longest match first.
        # if we have resources with a "similar" ID, e.g.
        # one resource contains the ID of another resource
        # playground-user and playground-user-foobar
        for resource in sorted(results, reverse=True):
            if tf_resource.id.startswith(resource.id):
                # the resource id has a prefix, e.g.
                # resource.id (terraform-resources): playground-stage
                # tf.id (ERv2): playground-stage-msk-cluster
                return resource
            if tf_resource.id.endswith(resource.id):
                # the resource id has a suffix
                # resource.id (terraform-resources): playground-stage
                # tf.id (ERv2): msk-cluster-playground-stage
                return resource
        raise KeyError(f"Resource {tf_resource} not found!")

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

    def upload_state(self) -> None:
        self._tf_state_push()

    def resource_changes(self, action: TfAction) -> TfResourceList:
        """Get the resource changes."""
        plan = json.loads(self._tf_run(self._path, ["show", "-json", "plan.out"]))
        return TfResourceList(
            resources=[
                TfResource(address=r["address"])
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

    def migrate_resources(self, source: TerraformCli) -> None:
        """Migrate the resources from source."""
        if not self.initialized or not source.initialized:
            raise ValueError("Terraform must be initialized before!")

        source_resources = source.resource_changes(TfAction.DESTROY)
        destionation_resources = self.resource_changes(TfAction.CREATE)

        if (
            not source_resources
            or not destionation_resources
            # I'm not sure if this is always true
            or len(source_resources) != len(destionation_resources)
        ):
            raise ValueError(
                "No resource changes found or the number of resources is different!"
            )

        for destionation_resource in destionation_resources:
            source_resource = source_resources[destionation_resource]
            if source_resource.id != destionation_resource.id:
                if self.progress_spinner:
                    self.progress_spinner.log(
                        f"[b red]Resource id mismatch! Please review it carefully![/]\n  {source_resource} -> {destionation_resource}"
                    )

            self.move_resource(
                source_state_file=source.state_file,
                source=source_resource,
                destination=destionation_resource,
            )

        if not self._dry_run:
            if self.progress_spinner:
                self.progress_spinner.stop()
            if not Confirm.ask(
                "\nEverything ok? Would you like to upload the modified terraform states",
                default=False,
            ):
                return

            if self.progress_spinner:
                self.progress_spinner.start()

            # finally push the terraform states
            self.upload_state()
            source.upload_state()
