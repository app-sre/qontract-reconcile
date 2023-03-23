import os
from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable
from typing import Optional

from reconcile.utils.exceptions import PrintToFileInGitRepositoryError
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
    ExternalResourceSpecInventory,
)
from reconcile.utils.git import is_file_in_git_repo


class TerraformConfigClient(ABC):
    """
    Clients that are responsible for collecting external resource specs and returning
    Terraform JSON configuration.
    """

    @abstractmethod
    def add_spec(self, spec: ExternalResourceSpec) -> None:
        """
        Add external resource specs that will be used to populate a Terraform JSON
        config.
        """

    @abstractmethod
    def populate_resources(self) -> None:
        """Populate the Terraform JSON configuration."""

    @abstractmethod
    def dump(
        self,
        existing_dir: Optional[str] = None,
    ) -> str:
        """Dump the Terraform JSON configuration to the filesystem."""

    @abstractmethod
    def dumps(self) -> str:
        """Return the Terraform JSON configuration as a string."""


class TerraformConfigClientCollection:
    """
    Collection of TerraformConfigClient for consolidating logic related collecting the
    clients and iterating through them, optionally concurrency as needed.
    """

    def __init__(self) -> None:
        self._clients: dict[str, TerraformConfigClient] = {}
        self.resource_spec_inventory: ExternalResourceSpecInventory = {}
        """Tracks the external resource specs across all clients in the collection."""

    def register_client(self, account_name: str, client: TerraformConfigClient) -> None:
        if account_name in self._clients:
            raise ClientAlreadyRegisteredError(
                f"Client already registered with the name: {account_name}"
            )

        self._clients[account_name] = client

    def add_specs(
        self,
        specs: Iterable[ExternalResourceSpec],
        account_filter: Optional[str] = None,
    ) -> None:
        """
        Add external resource specs
        :param specs: external resource specs to add
        :param account_filter: an account name that can optionally be used to filter out
                               any resources that don't match the account. If omitted,
                               all specs will be added.
        """

        for spec in specs:
            # If using an account filter and the account name doesn't match, skip the
            # resource.
            if account_filter and account_filter != spec.provisioner_name:
                continue
            try:
                self._clients[spec.provisioner_name].add_spec(spec)
            except KeyError:
                raise ClientNotRegisteredError(
                    f"There aren't any clients registered with the account name: {spec.provisioner_name}"
                )
            self.resource_spec_inventory[spec.id_object()] = spec

    def populate_resources(self) -> None:
        for client in self._clients.values():
            client.populate_resources()

    def dump(
        self,
        print_to_file: Optional[str] = None,
        existing_dirs: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        """
        Dump the Terraform JSON config to the filesystem.

        :param print_to_file: optionally write the Terraform JSON config to the
                              designated file path. This is helpful for troubleshooting
                              the Terraform JSON output as a single file.
        :param existing_dirs: a mapping of the account name to working directory for
                              the Terraform JSON configs
        :return: a mapping of the account names to working directories
        """
        if existing_dirs is None:
            working_dirs: dict[str, str] = {}
        else:
            working_dirs = existing_dirs

        if print_to_file:
            if is_file_in_git_repo(print_to_file):
                raise PrintToFileInGitRepositoryError(print_to_file)
            if os.path.isfile(print_to_file):
                os.remove(print_to_file)

        for account_name, client in self._clients.items():
            working_dirs[account_name] = client.dump()

            if print_to_file:
                with open(print_to_file, "a") as f:
                    f.write(f"##### {account_name} #####\n")
                    f.write(client.dumps())
                    f.write("\n")

        return working_dirs


class ClientAlreadyRegisteredError(Exception):
    pass


class ClientNotRegisteredError(Exception):
    pass
