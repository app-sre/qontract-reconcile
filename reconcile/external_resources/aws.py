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


class AWSElasticacheFactory(AWSDefaultResourceFactory):
    def _get_source_db_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self.er_inventory.get_inventory_spec(
            "aws", provisioner, "elasticache", identifier
        )

    def resolve(self, spec: ExternalResourceSpec) -> dict[str, Any]:
        """Resolve the elasticache resource specification and translate some attributes to AWS >= 5.60.0 provider format."""
        rvr = ResourceValueResolver(spec=spec, identifier_as_value=True)
        data = rvr.resolve()
        data["output_prefix"] = spec.output_prefix

        if "replication_group_id" not in data:
            data["replication_group_id"] = spec.identifier

        if cluster_mode := data.pop("cluster_mode", {}):
            for k, v in cluster_mode.items():
                data[k] = v

        if "parameter_group" in data:
            pg_data = rvr._get_values(data["parameter_group"])
            data["parameter_group"] = pg_data

        return data

    def validate(self, resource: ExternalResource) -> None:
        """Validate the elasticache resource specification."""
        data = resource.data
        if data.get("parameter_group"):
            if not data["parameter_group"].get("name"):
                data["parameter_group"]["name"] = f"{data['replication_group_id']}-pg"
            else:
                # prefix the parameter_group name with the replication_group_id
                data["parameter_group"]["name"] = (
                    f"{data['replication_group_id']}-{data['parameter_group']['name']}"
                )

            if (
                data.get("parameter_group_name")
                and data["parameter_group"]["name"] != data["parameter_group_name"]
            ):
                raise ValueError(
                    "Custom parameter_group set and parameter_group_name given. Either remove parameter_group_name or set it to the same value as parameter_group.name."
                )

            if not data.get("parameter_group_name"):
                # automatically set /aws/elasticache-defaults-1.yml/parameter_group_name to /aws/parameter-group-1.yml/name
                data["parameter_group_name"] = data["parameter_group"]["name"]


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
