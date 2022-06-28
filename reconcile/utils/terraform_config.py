from typing import Iterable, Optional, Protocol
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpecInventory,
    ExternalResourceSpec,
)

from reconcile.utils.ocm import OCMMap


class UnknownProvisionProviderError(Exception):
    pass


class ProvisionProviderAlreadyRegisteredError(Exception):
    pass


class TerraformClientProtocol(Protocol):
    def dump(
        self,
        print_to_file: Optional[str] = None,
        existing_dirs: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        ...

    def init_populate_specs(
        self, specs: Iterable[ExternalResourceSpec], account_name: Optional[str]
    ) -> None:
        ...

    def populate_resources(
        self, spec: ExternalResourceSpec, ocm_map: Optional[OCMMap] = None
    ):
        ...


class TerraformConfigProvider:
    """
    At a high-level, this class is responsible for generating Terraform configuration in
    JSON format from app-interface schemas/openshift/external-resource-1.yml objects.
    Usage example (mostly to demonstrate API):

    cp = TerraformConfigProvider()
    cp.register_terraform_client("aws", terrascript_aws_client)
    cp.init_spec_inventory(specs, provision_provider, provisioner_name)
    cp.populate_resources(ocm_map=ocm_map)
    cp.dump(print_to_file, existing_dirs=working_dirs)
    """

    def __init__(self):
        self.resource_spec_inventory: ExternalResourceSpecInventory = {}
        self._terraform_clients: dict[str, TerraformClientProtocol] = {}

    def register_terraform_client(
        self, provision_provider: str, client: TerraformClientProtocol
    ):
        if not self._terraform_clients.get(provision_provider):
            self._terraform_clients[provision_provider] = client
        else:
            raise ProvisionProviderAlreadyRegisteredError(
                f"There can only be one client for each provision provider, {provision_provider} was already registered"
            )

    def dump(
        self,
        print_to_file: Optional[str] = None,
        existing_dirs: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        # TODO: need to verify that passing in existing_dirs to each client will be
        # okay as long as they only modify what's needed.
        working_dirs = {}
        for client in self._terraform_clients.values():
            working_dirs.update(client.dump(print_to_file, existing_dirs))
        return working_dirs

    def init_spec_inventory(
        self, specs: Iterable[ExternalResourceSpec], provisioner_name: Optional[str]
    ) -> None:
        """
        Initiates resource specs from the definitions in app-interface
        (schemas/openshift/external-resource-1.yml).
        :param specs: external resource specs
        :param provisioner_name: name of the provisioner
        """
        for spec in specs:
            if provisioner_name and spec.provisioner_name != provisioner_name:
                continue
            self.resource_spec_inventory[spec.id_object()] = spec

        for client in self._terraform_clients.values():
            client.init_populate_specs(specs, provisioner_name)

    def populate_resources(self, ocm_map: Optional[OCMMap] = None) -> None:
        """
        Populates the terraform configuration from resource specs.
        :param ocm_map:
        """
        for spec in self.resource_spec_inventory.values():
            try:
                self._terraform_clients[spec.provision_provider].populate_resources(
                    spec, ocm_map=ocm_map
                )
            except KeyError:
                raise UnknownProvisionProviderError(spec.provision_provider)
