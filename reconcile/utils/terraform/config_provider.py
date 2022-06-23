from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional
from reconcile.utils.external_resource_spec import ExternalResourceSpecInventory
from reconcile.utils.external_resources import PROVIDER_AWS, get_external_resource_specs
from reconcile.utils.ocm import OCMMap

from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript


@dataclass
class TerraformConfigProvider:
    """
    At a high-level, this class is responsible for generating Terraform configuration in
    JSON format from app-interface schemas/openshift/external-resource-1.yml objects.

    Usage example (mostly to demonstrate API):

    cp = TerraformConfigProvider("terraform_resources", "qrtf", 20, provisioners, settings)
    cp.init_spec_inventory(namespaces, provision_provider, provisioner_name)
    cp.populate_resources(ocm_map=ocm_map)
    cp.dump(print_to_file, existing_dirs=working_dirs)
    """

    integration: str
    integration_prefix: str
    thread_pool_size: int
    provisioners: list[dict[str, Any]]
    settings: Optional[Mapping[str, Any]] = None

    def __post_init__(self):
        self.ts = Terrascript(
            self.integration,
            self.integration_prefix,
            self.thread_pool_size,
            self.provisioners,
            settings=self.settings,
        )

    def dump(
        self,
        print_to_file: Optional[str] = None,
        existing_dirs: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        return self.ts.dump(print_to_file, existing_dirs)

    def init_spec_inventory(
        self, namespaces: Iterable[Mapping[str, Any]], provisioner_name: Optional[str]
    ) -> None:
        self.ts.init_populate_specs(namespaces, provisioner_name)

    @property
    def resource_spec_inventory(self):
        return self.ts.resource_spec_inventory

    def populate_resources(self, ocm_map: Optional[OCMMap] = None) -> None:
        self.ts.populate_resources(ocm_map=ocm_map)
