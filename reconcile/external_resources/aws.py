import re
from abc import ABC, abstractmethod
from typing import Any

from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
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
    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None: ...

    def find_linked_resources(
        self, spec: ExternalResourceSpec
    ) -> set[ExternalResourceKey]:
        """Method to find dependant resources. Resources in this list
        will be reconciled every time the parent resource finishes its reconciliation."""
        return set()


class AWSDefaultResourceFactory(AWSResourceFactory):
    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]:
        return ResourceValueResolver(spec=spec, identifier_as_value=True).resolve()

    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None: ...


class AWSElasticacheFactory(AWSDefaultResourceFactory):
    def _get_source_db_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self.er_inventory.get_inventory_spec(
            "aws", provisioner, "elasticache", identifier
        )

    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]:
        """Resolve the elasticache resource specification and translate some attributes to AWS >= 5.60.0 provider format."""
        rvr = ResourceValueResolver(spec=spec, identifier_as_value=True)
        data = rvr.resolve()
        data["output_prefix"] = spec.output_prefix

        if "replication_group_id" not in data:
            data["replication_group_id"] = spec.identifier

        data["environment"] = spec.environment_type

        if cluster_mode := data.pop("cluster_mode", {}):
            for k, v in cluster_mode.items():
                data[k] = v

        if "parameter_group" in data:
            pg_data = rvr._get_values(data["parameter_group"])
            data["parameter_group"] = pg_data

        return data

    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None:
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
    TIMEOUT_RE = re.compile(r"^(?:(\d+)h)?\s*(?:(\d+)m)?$")
    TIMEOUT_UNITS = units = {"h": "hours", "m": "minutes"}

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

    def _get_region_from_az(self, az: str) -> str:
        if not az or len(az) < 2:
            raise ValueError(
                f"Invalid availability zone: '{az}'. Availability zone must have at least 2 characters."
            )
        if not az[-1].isalpha():
            raise ValueError(
                f"Invalid availability zone: '{az}'. The AZ should end with a letter (e.g., 'us-east-1a')."
            )
        return az[:-1]

    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]:
        rvr = ResourceValueResolver(spec=spec, identifier_as_value=True)
        data = rvr.resolve()

        data["output_prefix"] = spec.output_prefix

        if "parameter_group" in data:
            pg_data = rvr._get_values(data["parameter_group"])
            data["parameter_group"] = pg_data
        if (
            (blue_green_deployment := data.get("blue_green_deployment"))
            and (target := blue_green_deployment.get("target"))
            and (parameter_group := target.get("parameter_group"))
        ):
            data["blue_green_deployment"] = blue_green_deployment | {
                "target": target | {"parameter_group": rvr._get_values(parameter_group)}
            }
        if "replica_source" in data:
            sourcedb_spec = self._get_source_db_spec(
                spec.provisioner_name, data["replica_source"]
            )
            sourcedb = self.resolve(sourcedb_spec, module_conf)
            sourcedb_region = (
                sourcedb.get("region", None)
                or sourcedb_spec.provisioner["resources_default_region"]
            )
            data["replica_source"] = {
                "identifier": sourcedb["identifier"],
                "region": sourcedb_region,
                "blue_green_deployment": sourcedb.get("blue_green_deployment"),
            }
        # If AZ is set, but not the region, the region is got from the AZ
        if "availability_zone" in data and "region" not in data:
            data["region"] = self._get_region_from_az(data["availability_zone"])

        kms_key_id: str = data.get("kms_key_id", None)
        if kms_key_id and not kms_key_id.startswith("arn:"):
            data["kms_key_id"] = self._get_kms_key_spec(
                spec.provisioner_name, kms_key_id
            ).identifier

        # If not timeouts are set, set default timeouts according to the module reconcile timeout configuration
        # 5 minutes are substracted to let terraform finish gracefully before the Job is killed.
        if "timeouts" not in data:
            data["timeouts"] = {
                "create": f"{module_conf.reconcile_timeout_minutes - 5}m",
                "update": f"{module_conf.reconcile_timeout_minutes - 5}m",
                "delete": f"{module_conf.reconcile_timeout_minutes - 5}m",
            }
        return data

    def _get_timeout_minutes(
        self,
        timeout: str,
    ) -> int:
        if not (match := re.fullmatch(AWSRdsFactory.TIMEOUT_RE, timeout)):
            raise ValueError(
                f"Invalid RDS instance timeout format: {timeout}. Specify a duration using 'h' and 'm' only. E.g. 2h30m"
            )

        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        return hours * 60 + minutes

    def _validate_timeouts(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None:
        timeouts = resource.data.get("timeouts")
        if not timeouts:
            return

        if not isinstance(timeouts, dict):
            raise ValueError(
                "Timeouts must be a dictionary with 'create', 'update' and/or 'delete' keys."
            )

        allowed_keys = {"create", "update", "delete"}
        if unknown_keys := timeouts.keys() - allowed_keys:
            raise ValueError(
                f"Timeouts must be a dictionary with 'create', 'update' and/or 'delete' keys. Offending keys: {unknown_keys}."
            )

        for option, timeout in timeouts.items():
            timeout_minutes = self._get_timeout_minutes(timeout)
            if timeout_minutes >= module_conf.reconcile_timeout_minutes:
                raise ValueError(
                    f"RDS instance {option} timeout value {timeout_minutes} (minutes) must be lower than the module reconcile_timeout_minutes value {module_conf.reconcile_timeout_minutes}."
                )

    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None:
        self._validate_timeouts(resource, module_conf)

    def find_linked_resources(
        self, spec: ExternalResourceSpec
    ) -> set[ExternalResourceKey]:
        return {
            k
            for k, s in self.er_inventory.items()
            if s.provision_provider == "aws"
            and s.provider == "rds"
            and s.resource["replica_source"] == spec.identifier
            and not s.marked_to_delete
        }


class AWSMskFactory(AWSDefaultResourceFactory):
    def _get_source_db_spec(
        self, provisioner: str, identifier: str
    ) -> ExternalResourceSpec:
        return self.er_inventory.get_inventory_spec(
            "aws", provisioner, "msk", identifier
        )

    def resolve(
        self,
        spec: ExternalResourceSpec,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> dict[str, Any]:
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

    def validate(
        self,
        resource: ExternalResource,
        module_conf: ExternalResourceModuleConfiguration,
    ) -> None:
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
