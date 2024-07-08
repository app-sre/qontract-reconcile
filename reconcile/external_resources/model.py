import hashlib
import json
from abc import (
    ABC,
)
from collections.abc import (
    Iterable,
    Iterator,
    MutableMapping,
)
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from reconcile.gql_definitions.external_resources.external_resources_modules import (
    ExternalResourcesModuleV1,
)
from reconcile.gql_definitions.external_resources.external_resources_namespaces import (
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceRDSV1,
    NamespaceTerraformResourceRoleV1,
    NamespaceV1,
)
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)


class ExternalResourceValidationError(Exception):
    errors: list[str] = []

    def add_validation_error(self, msg: str) -> None:
        self.errors.append(msg)


class ExternalResourceKey(BaseModel, frozen=True):
    provision_provider: str
    provisioner_name: str
    provider: str
    identifier: str

    @staticmethod
    def from_spec(spec: ExternalResourceSpec) -> "ExternalResourceKey":
        return ExternalResourceKey(
            provision_provider=spec.provision_provider,
            provisioner_name=spec.provisioner_name,
            identifier=spec.identifier,
            provider=spec.provider,
        )

    def hash(self) -> str:
        return hashlib.md5(
            json.dumps(self.dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()

    @property
    def state_path(self) -> str:
        return f"{self.provision_provider}/{self.provisioner_name}/{self.provider}/{self.identifier}"


class ExternalResourcesInventory(MutableMapping):
    _inventory: dict[ExternalResourceKey, ExternalResourceSpec] = {}

    def __init__(self, namespaces: Iterable[NamespaceV1]) -> None:
        desired_providers = [
            (p, ns)
            for ns in namespaces
            for p in ns.external_resources or []
            if isinstance(p, NamespaceTerraformProviderResourceAWSV1) and p.resources
        ]

        desired_specs = [
            ExternalResourceSpec(
                provision_provider=p.provider,
                provisioner=p.provisioner.dict(),
                resource=r.dict(),
                namespace=ns.dict(),
            )
            for (p, ns) in desired_providers
            for r in p.resources
            if isinstance(
                r, NamespaceTerraformResourceRDSV1 | NamespaceTerraformResourceRoleV1
            )
            and r.managed_by_erv2
        ]

        for spec in desired_specs:
            self._inventory[ExternalResourceKey.from_spec(spec)] = spec

    def __getitem__(self, key: ExternalResourceKey) -> ExternalResourceSpec | None:
        return self._inventory[key]

    def __setitem__(self, key: ExternalResourceKey, spec: ExternalResourceSpec) -> None:
        self._inventory[key] = spec

    def __delitem__(self, key: ExternalResourceKey) -> None:
        del self._inventory[key]

    def __iter__(self) -> Iterator[ExternalResourceKey]:
        return iter(self._inventory)

    def __len__(self) -> int:
        return len(self._inventory)

    def get_inventory_spec(
        self, provision_provider: str, provisioner: str, provider: str, identifier: str
    ) -> ExternalResourceSpec:
        """Convinience method to find referenced specs in the inventory. For example, finding a sourcedb reference for an RDS instance."""
        key = ExternalResourceKey(
            provision_provider=provision_provider,
            provisioner_name=provisioner,
            provider=provider,
            identifier=identifier,
        )
        try:
            return self._inventory[key]
        except KeyError:
            msg = f"Resource spec not found: Provider {provider}, Id: {identifier}"
            raise FetchResourceError(msg)


class Action(StrEnum):
    DESTROY: str = "Destroy"
    APPLY: str = "Apply"


class ExternalResourceModuleKey(BaseModel, frozen=True):
    provision_provider: str
    provider: str


class ModuleInventory:
    inventory: dict[ExternalResourceModuleKey, ExternalResourcesModuleV1]

    def __init__(
        self, inventory: dict[ExternalResourceModuleKey, ExternalResourcesModuleV1]
    ):
        self.inventory = inventory

    def get_from_external_resource_key(
        self, key: ExternalResourceKey
    ) -> ExternalResourcesModuleV1:
        return self.inventory[
            ExternalResourceModuleKey(
                provision_provider=key.provision_provider, provider=key.provider
            )
        ]

    def get_from_spec(self, spec: ExternalResourceSpec) -> ExternalResourcesModuleV1:
        return self.inventory[
            ExternalResourceModuleKey(
                provision_provider=spec.provision_provider, provider=spec.provider
            )
        ]


def load_module_inventory(
    modules: Iterable[ExternalResourcesModuleV1],
) -> ModuleInventory:
    return ModuleInventory({
        ExternalResourceModuleKey(
            provision_provider=m.provision_provider, provider=m.provider
        ): m
        for m in modules
    })


class ExternalResourceModuleConfiguration(BaseModel, frozen=True):
    image: str = ""
    version: str = ""
    reconcile_drift_interval_minutes: int = -1000
    reconcile_timeout_minutes: int = -1000

    @property
    def image_version(self) -> str:
        return f"{self.image}:{self.version}"

    @staticmethod
    def resolve_configuration(
        module: ExternalResourcesModuleV1, spec: ExternalResourceSpec
    ) -> "ExternalResourceModuleConfiguration":
        # TODO: Modify resource schemas to include this attributes
        data = {
            "image": module.image,
            "version": module.default_version,
            "reconcile_drift_interval_minutes": module.reconcile_drift_interval_minutes,
            "reconcile_timeout_minutes": module.reconcile_timeout_minutes,
        }
        return ExternalResourceModuleConfiguration.parse_obj(data)


class Reconciliation(BaseModel, frozen=True):
    key: ExternalResourceKey
    resource_hash: str = ""
    input: str = ""
    action: Action = Action.APPLY
    module_configuration: ExternalResourceModuleConfiguration = (
        ExternalResourceModuleConfiguration()
    )


class ModuleProvisionData(ABC, BaseModel):
    pass


class TerraformModuleProvisionData(ModuleProvisionData):
    """Specific Provision Options for modules based on Terraform or CDKTF"""

    tf_state_bucket: str
    tf_state_region: str
    tf_state_dynamodb_table: str
    tf_state_key: str


class ExternalResourceProvision(BaseModel):
    """External resource app-interface attributes. They are not part of the resource but are needed
    for annotating secrets or other stuff
    """

    provision_provider: str
    provisioner: str
    provider: str
    identifier: str
    target_cluster: str
    target_namespace: str
    target_secret_name: str
    module_provision_data: ModuleProvisionData


class ExternalResource(BaseModel):
    data: dict[str, Any]
    provision: ExternalResourceProvision

    def hash(self) -> str:
        return hashlib.md5(
            json.dumps(self.data, sort_keys=True).encode("utf-8")
        ).hexdigest()
