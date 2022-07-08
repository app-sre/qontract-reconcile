from abc import ABC, abstractmethod
from typing import Iterable, Optional

from reconcile.utils.external_resource_spec import ExternalResourceSpec


class TerraformConfigClient(ABC):
    """
    Clients that are responsible for collecting external resource specs and returning
    Terraform JSON configuration.
    """

    @abstractmethod
    def add_specs(self, specs: Iterable[ExternalResourceSpec]) -> None:
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
        print_to_file: Optional[str] = None,
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

    def register_client(self, client_name: str, client: TerraformConfigClient) -> None:
        if client_name in self._clients:
            raise ClientAlreadyRegisteredError(
                f"Client already registered with the name: {client_name}"
            )

        self._clients[client_name] = client

    def add_specs(self, client_name: str, specs: Iterable[ExternalResourceSpec]):
        try:
            self._clients[client_name].add_specs(specs)
        except KeyError:
            raise ClientNotRegisteredError(
                f"There aren't any clients registered with the name: {client_name}"
            )

    def populate_resources(self) -> None:
        for client in self._clients.values():
            client.populate_resources()

    def dump(self) -> dict[str, str]:
        working_dirs = {}

        for client_name, client in self._clients.items():
            working_dirs[client_name] = client.dump()

        return working_dirs


class ClientAlreadyRegisteredError(Exception):
    pass


class ClientNotRegisteredError(Exception):
    pass
