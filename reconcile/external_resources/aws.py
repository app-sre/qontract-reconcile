from abc import ABC, abstractmethod
from typing import Any

from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourcesInventory,
)
from reconcile.utils.external_resource_spec import (
    ExternalResourceSpec,
)
from reconcile.utils.external_resources import ResourceValueResolver
from reconcile.utils.secret_reader import SecretReaderBase


class AWSResourceFactory(ABC):
    def __init__(
        self, er_inventory: ExternalResourcesInventory, secret_reader: SecretReaderBase
    ):
        self.er_inventory = er_inventory
        self.secret_reader = secret_reader

    @abstractmethod
    def resolve(self, spec: ExternalResourceSpec) -> dict[str, Any]: ...

    @abstractmethod
    def validate(self, resource: ExternalResource) -> None: ...


class AWSDefaultResourceFactory(AWSResourceFactory):
    def resolve(self, spec: ExternalResourceSpec) -> dict[str, Any]:
        return ResourceValueResolver(spec=spec, identifier_as_value=True).resolve()

    def validate(self, resource: ExternalResource) -> None: ...


class AWSRdsFactory(AWSDefaultResourceFactory):
    def _get_source_db_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self.er_inventory.get_inventory_spec(
            "aws", provisioner, "rds", identifier
        )

    def _get_kms_key_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self.er_inventory.get_inventory_spec(
            "aws", provisioner, "kms", identifier
        )

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

    def validate(self, resource: ExternalResource) -> None: ...


class AWSMskFactory(AWSDefaultResourceFactory):
    def _get_source_db_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self.er_inventory.get_inventory_spec(
            "aws", provisioner, "msk", identifier
        )

    def resolve(self, spec: ExternalResourceSpec) -> dict[str, Any]:
        rvr = ResourceValueResolver(spec=spec, identifier_as_value=True)
        data = rvr.resolve()
        data["output_prefix"] = spec.output_prefix

        scram_enabled = (
            data.get("client_authentication", {}).get("sasl", {}).get("scram", False)
        )
        data["scram_users"] = {}
        if scram_enabled:
            if not data.get("users", []):
                raise ValueError(
                    "users attribute must be given when client_authentication.sasl.scram is enabled."
                )
            data["scram_users"] = {
                user["name"]: self.secret_reader.read_all(user["secret"])
                for user in data["users"]
            }
            # the users attribute is not needed in the final data
            del data["users"]
        return data

    def validate(self, resource: ExternalResource) -> None:
        data = resource.data
        if (
            data["number_of_broker_nodes"]
            % len(data["broker_node_group_info"]["client_subnets"])
            != 0
        ):
            raise ValueError(
                "number_of_broker_nodes must be a multiple of the number of specified client subnets."
            )
        # validate user objects
        for user, secret in data["scram_users"].items():
            if secret.keys() != {"password", "username"}:
                raise ValueError(
                    f"MSK user '{user}' secret must contain only 'username' and 'password' keys!"
                )
