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


class ResourceStatus(StrEnum):
    CREATED: str = "CREATED"
    DELETED: str = "DELETED"
    ABANDONED: str = "ABANDONED"
    NOT_EXISTS: str = "NOT_EXISTS"
    IN_PROGRESS: str = "IN_PROGRESS"
    DELETE_IN_PROGRESS: str = "DELETE_IN_PROGRESS"
    ERROR: str = "ERROR"
    PENDING_SECRET_SYNC: str = "PENDING_SECRET_SYNC"
    RECONCILIATION_REQUESTED: str = "RECONCILIATION_REQUESTED"

    @property
    def is_in_progress(self) -> bool:
        return self in {ResourceStatus.IN_PROGRESS, ResourceStatus.DELETE_IN_PROGRESS}

    @property
    def needs_secret_sync(self) -> bool:
        return self == ResourceStatus.PENDING_SECRET_SYNC

    @property
    def has_errors(self) -> bool:
        return self == ResourceStatus.ERROR


class ExternalResourceState(BaseModel):
    key: ExternalResourceKey
    ts: datetime
    resource_status: ResourceStatus
    reconciliation: Reconciliation


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

    def _get_value(self, item: Mapping[str, Any], key: str, _type: str = "S") -> Any:
        return item[key][_type]

    def deserialize(
        self,
        item: Mapping[str, Any],
        partial_data: bool = False,
    ) -> ExternalResourceState:
        _key = self._get_value(item, self.ER_KEY, _type="M")
        key = ExternalResourceKey(
            provision_provider=self._get_value(_key, self.ER_KEY_PROVISION_PROVIDER),
            provisioner_name=self._get_value(_key, self.ER_KEY_PROVISIONER_NAME),
            provider=self._get_value(_key, self.ER_KEY_PROVIDER),
            identifier=self._get_value(_key, self.ER_KEY_IDENTIFIER),
        )
        _reconciliation = self._get_value(item, self.RECONC, _type="M")

        if partial_data:
            r = Reconciliation(
                key=key,
                resource_hash=self._get_value(
                    _reconciliation, self.RECONC_RESOURCE_HASH
                ),
            )
        else:
            _modconf = self._get_value(_reconciliation, self.MODCONF, _type="M")
            r = Reconciliation(
                key=key,
                resource_hash=self._get_value(
                    _reconciliation, self.RECONC_RESOURCE_HASH
                ),
                input=self._get_value(_reconciliation, self.RECONC_INPUT),
                action=self._get_value(_reconciliation, self.RECONC_ACTION),
                module_configuration=ExternalResourceModuleConfiguration(
                    image=self._get_value(_modconf, self.MODCONF_IMAGE),
                    version=self._get_value(_modconf, self.MODCONF_VERSION),
                    reconcile_drift_interval_minutes=self._get_value(
                        _modconf, self.MODCONF_DRIFT_MINS, _type="N"
                    ),
                    reconcile_timeout_minutes=self._get_value(
                        _modconf, self.MODCONF_TIMEOUT_MINS, _type="N"
                    ),
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
                        }
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
        for item in self.aws_api.dynamodb.boto3_client.scan(
            TableName=self._table, ProjectionExpression=self.PARTIALS_PROJECTED_VALUES
        ).get("Items", []):
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
