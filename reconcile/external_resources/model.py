import base64
import hashlib
import json
from abc import (
    ABC,
)
from collections.abc import ItemsView, Iterable, KeysView, ValuesView
from enum import Enum
from typing import Any

from pydantic import BaseModel

from reconcile.gql_definitions.external_resources.external_resources_namespaces import (
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceV1,
)
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

    def digest(self) -> str:
        digest = hashlib.md5(
            json.dumps(self.dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()
        return digest

    @property
    def state_path(self) -> str:
        return f"{self.provision_provider}/{self.provisioner_name}/{self.provider}/{self.identifier}"


class ExternalResourcesInventory:
    _inventory: dict[ExternalResourceKey, ExternalResourceSpec] = {}

    def __init__(self, namespaces: Iterable[NamespaceV1]) -> None:
        # TODO: Sharding/filtering
        for ns in namespaces:
            if ns.name != "external-resources-poc":
                continue
            for erp in ns.external_resources or []:
                if (
                    not isinstance(erp, NamespaceTerraformProviderResourceAWSV1)
                    or not erp.resources
                ):
                    continue
                for er in erp.resources:
                    # Using this class is far from ideal as it uses
                    # generic dicts. This might need improved logic.
                    spec = ExternalResourceSpec(
                        provision_provider=erp.provider,
                        provisioner=erp.provisioner.dict(),
                        resource=er.dict(),
                        namespace=ns.dict(),
                    )
                    key = ExternalResourceKey.from_spec(spec)
                    self.set(key, spec)
                break

    def get(self, key: ExternalResourceKey) -> ExternalResourceSpec | None:
        return self._inventory.get(key)

    def set(self, key: ExternalResourceKey, spec: ExternalResourceSpec) -> None:
        self._inventory[key] = spec

    def items(self) -> ItemsView[ExternalResourceKey, ExternalResourceSpec]:
        return self._inventory.items()

    def values(self) -> ValuesView[ExternalResourceSpec]:
        return self._inventory.values()

    def keys(self) -> KeysView[ExternalResourceKey]:
        return self._inventory.keys()


class Action(str, Enum):
    DESTROY: str = "Destroy"
    APPLY: str = "Apply"


class ExternalResourceModuleKey(BaseModel, frozen=True):
    provision_provider: str
    provider: str


class ExternalResourceModule(BaseModel):
    provision_provider: str
    provider: str
    module_type: str
    image: str
    default_version: str
    reconcile_drift_interval_minutes: int
    reconcile_timeout_minutes: int


class ModuleInventory:
    inventory: dict[ExternalResourceModuleKey, ExternalResourceModule]

    def __init__(
        self, inventory: dict[ExternalResourceModuleKey, ExternalResourceModule]
    ):
        self.inventory = inventory

    def get_from_external_resource_key(
        self, key: ExternalResourceKey
    ) -> ExternalResourceModule:
        return self.inventory[
            ExternalResourceModuleKey(
                provision_provider=key.provision_provider, provider=key.provider
            )
        ]

    def get_from_spec(self, spec: ExternalResourceSpec) -> ExternalResourceModule:
        return self.inventory[
            ExternalResourceModuleKey(
                provision_provider=spec.provision_provider, provider=spec.provider
            )
        ]


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
        module: ExternalResourceModule, spec: ExternalResourceSpec
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
    resource_digest: str = ""
    input: str = ""
    action: Action = Action.APPLY
    module_configuration: ExternalResourceModuleConfiguration = (
        ExternalResourceModuleConfiguration()
    )


class ExternalResourcesSettings(BaseModel):
    """Class with Settings for all the supported external resources provisioners"""

    # Terraform / CDKTF
    tf_state_bucket: str
    tf_state_region: str
    tf_state_dynamodb_table: str
    # Others ...
    state_dynamodb_table: str
    state_dynamodb_index: str


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
    for annotating secrets or other stuff"""

    provision_provider: str  # aws
    provisioner: str  # ter-int-dev
    provider: str  # aws-iam-role
    identifier: str
    target_cluster: str
    target_namespace: str
    target_secret_name: str
    module_provision_data: ModuleProvisionData


class ExternalResource(BaseModel):
    data: dict[str, Any]
    provision: ExternalResourceProvision

    def digest(self) -> str:
        digest = hashlib.md5(
            json.dumps(self.data, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return digest

    def serialize_input(self) -> str:
        return base64.b64encode(json.dumps(self.dict()).encode()).decode()
