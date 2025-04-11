import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from reconcile.external_resources.model import (
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    Reconciliation,
    ReconciliationStatus,
    Resources,
    ResourcesSpec,
    ResourceStatus,
)
from reconcile.utils.aws_api_typed.api import AWSApi

DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class StateNotFoundError(Exception):
    pass


class ReconcileStatus(StrEnum):
    SUCCESS: str = "SUCCESS"
    ERROR: str = "ERROR"
    IN_PROGRESS: str = "IN_PROGRESS"
    NOT_EXISTS: str = "NOT_EXISTS"


class ExternalResourceState(BaseModel):
    key: ExternalResourceKey
    ts: datetime
    resource_status: ResourceStatus
    reconciliation: Reconciliation

    def update_resource_status(
        self, reconciliation_status: ReconciliationStatus
    ) -> None:
        if self.reconciliation_needs_state_update(reconciliation_status):
            self.ts = datetime.now()
            self.resource_status = reconciliation_status.resource_status

    def reconciliation_needs_state_update(
        self, reconciliation_status: ReconciliationStatus
    ) -> bool:
        return (
            self.resource_status.is_in_progress or self.resource_status.does_not_exist
        ) and not reconciliation_status.resource_status.is_in_progress


class DynamoDBStateAdapter:
    # Table PK
    ER_KEY_HASH = "external_resource_key_hash"

    RESOURCE_STATUS = "resource_status"
    TIMESTAMP = "time_stamp"

    ER_KEY = "external_resource_key"
    ER_KEY_PROVISION_PROVIDER = "provision_provider"
    ER_KEY_PROVISIONER_NAME = "provisioner_name"
    ER_KEY_PROVIDER = "provider"
    ER_KEY_IDENTIFIER = "identifier"

    RECONC = "reconciliation"
    RECONC_RESOURCE_HASH = "resource_hash"
    RECONC_INPUT = "input"
    RECONC_ACTION = "action"

    MODCONF = "module_configuration"
    MODCONF_IMAGE = "image"
    MODCONF_VERSION = "version"
    MODCONF_DRIFT_MINS = "drift_detection_minutes"
    MODCONF_TIMEOUT_MINS = "timeout_minutes"
    MODCONF_RESOURCES = "resources"
    MODCONF_RESOURCES_REQUESTS = "requests"
    MODCONF_RESOURCES_REQUESTS_CPU = "cpu"
    MODCONF_RESOURCES_REQUESTS_MEMORY = "memory"
    MODCONF_RESOURCES_LIMITS = "limits"
    MODCONF_RESOURCES_LIMITS_CPU = "cpu"
    MODCONF_RESOURCES_LIMITS_MEMORY = "memory"

    def _get_value(self, item: Mapping[str, Any], key: str, type: str = "S") -> Any:
        if item[key][type] == "None":
            return None
        return item[key][type]

    def _build_resources(self, modconf: Mapping[str, Any]) -> Resources | None:
        if self.MODCONF_RESOURCES not in modconf:
            return Resources()
        mc_resources = self._get_value(modconf, self.MODCONF_RESOURCES, type="M")
        mc_resources_requests = self._get_value(
            mc_resources, self.MODCONF_RESOURCES_REQUESTS, type="M"
        )
        mc_resources_limits = self._get_value(
            mc_resources, self.MODCONF_RESOURCES_LIMITS, type="M"
        )
        return Resources(
            requests=ResourcesSpec(
                cpu=self._get_value(
                    mc_resources_requests, self.MODCONF_RESOURCES_REQUESTS_CPU
                ),
                memory=self._get_value(
                    mc_resources_requests, self.MODCONF_RESOURCES_REQUESTS_MEMORY
                ),
            ),
            limits=ResourcesSpec(
                cpu=self._get_value(
                    mc_resources_limits, self.MODCONF_RESOURCES_LIMITS_CPU
                ),
                memory=self._get_value(
                    mc_resources_limits, self.MODCONF_RESOURCES_LIMITS_MEMORY
                ),
            ),
        )

    def deserialize(
        self,
        item: Mapping[str, Any],
        partial_data: bool = False,
    ) -> ExternalResourceState:
        key_ = self._get_value(item, self.ER_KEY, type="M")
        key = ExternalResourceKey(
            provision_provider=self._get_value(key_, self.ER_KEY_PROVISION_PROVIDER),
            provisioner_name=self._get_value(key_, self.ER_KEY_PROVISIONER_NAME),
            provider=self._get_value(key_, self.ER_KEY_PROVIDER),
            identifier=self._get_value(key_, self.ER_KEY_IDENTIFIER),
        )
        reconciliation = self._get_value(item, self.RECONC, type="M")

        if partial_data:
            r = Reconciliation(
                key=key,
                resource_hash=self._get_value(
                    reconciliation, self.RECONC_RESOURCE_HASH
                ),
            )
        else:
            modconf = self._get_value(reconciliation, self.MODCONF, type="M")
            r = Reconciliation(
                key=key,
                resource_hash=self._get_value(
                    reconciliation, self.RECONC_RESOURCE_HASH
                ),
                input=self._get_value(reconciliation, self.RECONC_INPUT),
                action=self._get_value(reconciliation, self.RECONC_ACTION),
                module_configuration=ExternalResourceModuleConfiguration(
                    image=self._get_value(modconf, self.MODCONF_IMAGE),
                    version=self._get_value(modconf, self.MODCONF_VERSION),
                    reconcile_drift_interval_minutes=self._get_value(
                        modconf, self.MODCONF_DRIFT_MINS, type="N"
                    ),
                    reconcile_timeout_minutes=self._get_value(
                        modconf, self.MODCONF_TIMEOUT_MINS, type="N"
                    ),
                    resources=self._build_resources(modconf),
                ),
            )

        return ExternalResourceState(
            key=key,
            ts=self._get_value(item, self.TIMESTAMP),
            resource_status=self._get_value(item, self.RESOURCE_STATUS),
            reconciliation=r,
        )

    def serialize(self, state: ExternalResourceState) -> dict[str, Any]:
        return {
            self.ER_KEY_HASH: {"S": state.key.hash()},
            self.TIMESTAMP: {"S": state.ts.isoformat()},
            self.RESOURCE_STATUS: {"S": state.resource_status.value},
            self.ER_KEY: {
                "M": {
                    self.ER_KEY_PROVISION_PROVIDER: {"S": state.key.provision_provider},
                    self.ER_KEY_PROVISIONER_NAME: {"S": state.key.provisioner_name},
                    self.ER_KEY_PROVIDER: {"S": state.key.provider},
                    self.ER_KEY_IDENTIFIER: {"S": state.key.identifier},
                }
            },
            self.RECONC: {
                "M": {
                    self.RECONC_RESOURCE_HASH: {
                        "S": state.reconciliation.resource_hash
                    },
                    self.RECONC_ACTION: {"S": state.reconciliation.action.value},
                    self.RECONC_INPUT: {"S": state.reconciliation.input},
                    self.MODCONF: {
                        "M": {
                            self.MODCONF_IMAGE: {
                                "S": state.reconciliation.module_configuration.image
                            },
                            self.MODCONF_VERSION: {
                                "S": state.reconciliation.module_configuration.version
                            },
                            self.MODCONF_DRIFT_MINS: {
                                "N": str(
                                    state.reconciliation.module_configuration.reconcile_drift_interval_minutes
                                )
                            },
                            self.MODCONF_TIMEOUT_MINS: {
                                "N": str(
                                    state.reconciliation.module_configuration.reconcile_timeout_minutes
                                )
                            },
                            self.MODCONF_RESOURCES: {
                                "M": {
                                    self.MODCONF_RESOURCES_REQUESTS: {
                                        "M": {
                                            self.MODCONF_RESOURCES_REQUESTS_CPU: {
                                                "S": str(
                                                    state.reconciliation.module_configuration.resources.requests.cpu
                                                )
                                            },
                                            self.MODCONF_RESOURCES_REQUESTS_MEMORY: {
                                                "S": str(
                                                    state.reconciliation.module_configuration.resources.requests.memory
                                                )
                                            },
                                        }
                                    },
                                    self.MODCONF_RESOURCES_LIMITS: {
                                        "M": {
                                            self.MODCONF_RESOURCES_LIMITS_CPU: {
                                                "S": str(
                                                    state.reconciliation.module_configuration.resources.limits.cpu
                                                )
                                            },
                                            self.MODCONF_RESOURCES_LIMITS_MEMORY: {
                                                "S": str(
                                                    state.reconciliation.module_configuration.resources.limits.memory
                                                )
                                            },
                                        }
                                    },
                                }
                            },
                        },
                    },
                }
            },
        }


class ExternalResourcesStateDynamoDB:
    PARTIALS_PROJECTED_VALUES = ",".join([
        DynamoDBStateAdapter.ER_KEY,
        DynamoDBStateAdapter.TIMESTAMP,
        DynamoDBStateAdapter.RESOURCE_STATUS,
        f"{DynamoDBStateAdapter.RECONC}.{DynamoDBStateAdapter.RECONC_RESOURCE_HASH}",
    ])

    def __init__(self, aws_api: AWSApi, table_name: str) -> None:
        self.adapter = DynamoDBStateAdapter()
        self.aws_api = aws_api
        self._table = table_name
        self.partial_resources = self._get_partial_resources()

    def get_external_resource_state(
        self, key: ExternalResourceKey
    ) -> ExternalResourceState:
        data = self.aws_api.dynamodb.boto3_client.get_item(
            TableName=self._table,
            ConsistentRead=True,
            Key={self.adapter.ER_KEY_HASH: {"S": key.hash()}},
        )
        if "Item" in data:
            return self.adapter.deserialize(data["Item"])
        else:
            return ExternalResourceState(
                key=key,
                ts=datetime.now(UTC),
                resource_status=ResourceStatus.NOT_EXISTS,
                reconciliation=Reconciliation(key=key),
                reconciliation_errors=0,
            )

    def set_external_resource_state(
        self,
        state: ExternalResourceState,
    ) -> None:
        self.aws_api.dynamodb.boto3_client.put_item(
            TableName=self._table, Item=self.adapter.serialize(state)
        )

    def del_external_resource_state(self, key: ExternalResourceKey) -> None:
        self.aws_api.dynamodb.boto3_client.delete_item(
            TableName=self._table,
            Key={self.adapter.ER_KEY_HASH: {"S": key.hash()}},
        )

    def _get_partial_resources(
        self,
    ) -> dict[ExternalResourceKey, ExternalResourceState]:
        """A Partial Resoure is the minimum resource data reguired
        to check if a resource has been removed from the configuration.
        Getting less data from DynamoDb saves money and the logic does not need it.
        """
        logging.debug("Getting Managed resources from DynamoDb")
        partials = {}
        paginator = self.aws_api.dynamodb.boto3_client.get_paginator("scan")
        pages = paginator.paginate(
            TableName=self._table,
            ProjectionExpression=self.PARTIALS_PROJECTED_VALUES,
            ConsistentRead=True,
            PaginationConfig={"PageSize": 1000},
        )
        for page in pages:
            for item in page.get("Items", []):
                s = self.adapter.deserialize(item, partial_data=True)
                partials[s.key] = s
        return partials

    def get_all_resource_keys(self) -> set[ExternalResourceKey]:
        return set(self.partial_resources)

    def get_keys_by_status(
        self, resource_status: ResourceStatus
    ) -> set[ExternalResourceKey]:
        return {
            k
            for k, v in self.partial_resources.items()
            if v.resource_status == resource_status
        }

    def update_resource_status(
        self, key: ExternalResourceKey, status: ResourceStatus
    ) -> None:
        self.aws_api.dynamodb.boto3_client.update_item(
            TableName=self._table,
            Key={self.adapter.ER_KEY_HASH: {"S": key.hash()}},
            UpdateExpression="set resource_status=:new_value",
            ExpressionAttributeValues={":new_value": {"S": status.value}},
            ReturnValues="UPDATED_NEW",
        )
