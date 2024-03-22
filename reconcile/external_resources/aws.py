from abc import ABC, abstractmethod
from typing import Any

from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceKey,
    ExternalResourcesInventory,
)
from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.external_resources import ResourceValueResolver
from reconcile.utils.secret_reader import SecretReaderBase

# class AWSHelper:
#     @staticmethod
#     def region_from_az(az: str = "") -> str | None:
#         if len(az) > 1:
#             return az[:-1]

#         raise ValueError(f"Invalid AZ {az}")

#     @staticmethod
#     def rds_instance_arn(region: str, account: str, identifier: str) -> str:
#         return f"arn:aws:rds:{region}:{account}:instance:{identifier}"


class AWSResourceFactory(ABC):
    def __init__(
        self, er_inventory: ExternalResourcesInventory, secrets_reader: SecretReaderBase
    ):
        self.er_inventory = er_inventory
        self.secrets_reader = secrets_reader

    def _get_inventory_spec(
        self, provision_provider: str, provisioner: str, provider: str, identifier: str
    ) -> ExternalResourceSpec:
        key = ExternalResourceKey(
            provision_provider=provision_provider,
            provisioner_name=provisioner,
            provider=provider,
            identifier=identifier,
        )
        spec = self.er_inventory.get(key)
        if not spec:
            msg = f"Resource spec not found: Provider {provider}, Id: {identifier}"
            raise FetchResourceError(msg)
        return spec

    @abstractmethod
    def resolve(self, spec: ExternalResourceSpec) -> dict[str, Any]: ...

    @abstractmethod
    def validate(self, resource: ExternalResource) -> None: ...


class AWSDefaultResourceFactory(AWSResourceFactory):
    def __init__(
        self, er_inventory: ExternalResourcesInventory, secrets_reader: SecretReaderBase
    ):
        self.er_inventory = er_inventory
        self.secrets_reader = secrets_reader

    def resolve(self, spec: ExternalResourceSpec) -> dict[str, Any]:
        return ResourceValueResolver(spec=spec, identifier_as_value=True).resolve()

    def validate(self, resource: ExternalResource) -> None: ...


class AWSRdsFactory(AWSDefaultResourceFactory):
    def _get_source_db_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self._get_inventory_spec("aws", provisioner, "rds", identifier)

    def _get_kms_key_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self._get_inventory_spec("aws", provisioner, "kms", identifier)

    def resolve(self, spec: ExternalResourceSpec) -> dict[str, Any]:
        rvr = ResourceValueResolver(spec=spec, identifier_as_value=True)
        data = rvr.resolve()

        data["output_prefix"] = spec.output_prefix

        if "parameter_group" in data:
            pg_data = rvr._get_values(data["parameter_group"])
            data["parameter_group"] = pg_data
        if "old_parameter_group" in data:
            old_pg_data = rvr._get_values(data["old_parameter_group"])
            data["old_parameter_group"] = old_pg_data
        if "replica_source" in data:
            sourcedb_spec = self._get_source_db_spec(
                spec.provisioner_name, data["replica_source"]
            )
            sourcedb = self.resolve(sourcedb_spec)
            sourcedb_region = (
                sourcedb.get("region", None)
                or sourcedb_spec.provisioner["resources_default_region"]
            )
            data["replica_source"] = {
                "identifier": sourcedb["identifier"],
                "region": sourcedb_region,
            }

        kms_key_id: str = data.get("kms_key_id", None)
        if kms_key_id and not kms_key_id.startswith("arn:"):
            data["kms_key_id"] = self._get_kms_key_spec(
                spec.provisioner_name, kms_key_id
            ).identifier

        return data

    def validate(self, resource: ExternalResource) -> None:
        ...
        # errors: list[str] = []

        # if "ca_cert" in resource.data:
        #     try:
        #         s = VaultSecret(**resource.data["ca_cert"])
        #         self.secrets_reader.read_secret(s)
        #     except SecretNotFound:
        #         errors.append(
        #             "Secret referenced in ca_cert attribute not found in the Secrets Engine: "
        #             + str(resource.data["ca_cert"])
        #         )
        #     except Exception as e:
        #         errors.append("Error finding Secret %s" + str(e))

        # if errors:
        #     raise ExternalResourceValidationError(errors)
