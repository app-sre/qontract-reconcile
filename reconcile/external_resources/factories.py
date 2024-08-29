from abc import (
    ABC,
    abstractmethod,
)
from typing import Generic, TypeVar

from reconcile.external_resources.aws import (
    AWSDefaultResourceFactory,
    AWSMskFactory,
    AWSRdsFactory,
    AWSResourceFactory,
)
from reconcile.external_resources.meta import QONTRACT_INTEGRATION
from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceKey,
    ExternalResourceProvision,
    ExternalResourcesInventory,
    ModuleInventory,
    ModuleProvisionData,
    TerraformModuleProvisionData,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.secret_reader import SecretReaderBase

T = TypeVar("T")

AWS_DEFAULT_TAGS = [
    {
        "tags": {
            "app": "app-sre-infra",
        }
    }
]


class ObjectFactory(Generic[T]):
    def __init__(self) -> None:
        self._factories: dict[str, T] = {}

    def register_factory(self, id: str, t: T) -> None:
        self._factories[id] = t

    def get_factory(self, id: str) -> T:
        return self._factories[id]


class ExternalResourceFactory(ABC):
    @abstractmethod
    def create_external_resource(self, spec: ExternalResourceSpec) -> ExternalResource:
        pass

    @abstractmethod
    def validate_external_resource(self, resource: ExternalResource) -> None:
        pass


class ModuleProvisionDataFactory(ABC):
    @abstractmethod
    def create_provision_data(self, ers: ExternalResourceSpec) -> ModuleProvisionData:
        pass


class TerraformModuleProvisionDataFactory(ModuleProvisionDataFactory):
    def __init__(self, settings: ExternalResourcesSettingsV1):
        self.settings = settings

    def create_provision_data(
        self, spec: ExternalResourceSpec
    ) -> TerraformModuleProvisionData:
        key = ExternalResourceKey.from_spec(spec)

        return TerraformModuleProvisionData(
            tf_state_bucket=self.settings.tf_state_bucket,
            tf_state_region=self.settings.tf_state_region,
            tf_state_dynamodb_table=self.settings.tf_state_dynamodb_table,
            tf_state_key=key.state_path + "/terraform.tfstate",
        )


def setup_aws_resource_factories(
    er_inventory: ExternalResourcesInventory, secret_reader: SecretReaderBase
) -> ObjectFactory[AWSResourceFactory]:
    f = ObjectFactory[AWSResourceFactory]()
    f.register_factory("rds", AWSRdsFactory(er_inventory, secret_reader))
    f.register_factory("msk", AWSMskFactory(er_inventory, secret_reader))
    f.register_factory(
        "default", AWSDefaultResourceFactory(er_inventory, secret_reader)
    )
    return f


class AWSExternalResourceFactory(ExternalResourceFactory):
    def __init__(
        self,
        module_inventory: ModuleInventory,
        er_inventory: ExternalResourcesInventory,
        secret_reader: SecretReaderBase,
        provision_factories: ObjectFactory[ModuleProvisionDataFactory],
        resource_factories: ObjectFactory[AWSResourceFactory],
    ):
        self.provision_factories = provision_factories
        self.resource_factories = resource_factories
        self.module_inventory = module_inventory
        self.er_inventory = er_inventory
        self.secret_reader = secret_reader

    def create_external_resource(self, spec: ExternalResourceSpec) -> ExternalResource:
        f = self.resource_factories.get_factory(spec.provider)
        data = f.resolve(spec)
        data["tags"] = spec.tags(integration=QONTRACT_INTEGRATION)
        data["default_tags"] = AWS_DEFAULT_TAGS

        region = data.get("region")
        if region:
            if region not in spec.provisioner["supported_deployment_regions"]:
                raise ValueError(region)
        else:
            region = spec.provisioner["resources_default_region"]
        data["region"] = region

        module_type = self.module_inventory.get_from_spec(spec).module_type
        provision_factory = self.provision_factories.get_factory(module_type)
        module_provision_data = provision_factory.create_provision_data(spec)

        provision = ExternalResourceProvision(
            provision_provider=spec.provision_provider,
            provisioner=spec.provisioner_name,
            provider=spec.provider,
            identifier=spec.identifier,
            target_cluster=spec.cluster_name,
            target_namespace=spec.namespace_name,
            target_secret_name=spec.output_resource_name,
            module_provision_data=module_provision_data,
        )

        return ExternalResource(data=data, provision=provision)

    def validate_external_resource(self, resource: ExternalResource) -> None:
        f = self.resource_factories.get_factory(resource.provision.provider)
        f.validate(resource)
