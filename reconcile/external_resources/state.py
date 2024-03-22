import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import boto3
from pydantic import BaseModel

from reconcile.external_resources.model import (
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    Reconciliation,
)

DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class StateNotFoundError(Exception):
    pass


class ReconcileStatus(str, Enum):
    SUCCESS: str = "SUCCESS"
    ERROR: str = "ERROR"
    IN_PROGRESS: str = "IN_PROGRESS"
    NOT_EXISTS: str = "NOT_EXISTS"


class ResourceStatus(str, Enum):
    CREATED: str = "CREATED"
    DELETED: str = "DELETED"
    ABANDONED: str = "ABANDONED"
    NOT_EXISTS: str = "NOT_EXISTS"
    IN_PROGRESS: str = "IN_PROGRESS"
    DELETE_IN_PROGRESS: str = "DELETE_IN_PROGRESS"
    ERROR: str = "ERROR"


class ExternalResourceState(BaseModel):
    key: ExternalResourceKey
    ts: datetime
    resource_status: ResourceStatus
    resource_digest: str = ""
    reconciliation: Reconciliation
    reconciliation_errors: int = 0


# class EnhancedJsonEncoder(JSONEncoder):
#     def default(self, obj: Any) -> Any:
#         if isinstance(obj, datetime):
#             return obj.isoformat()
#         elif dataclasses.is_dataclass(obj):
#             return dataclasses.asdict(obj)


# class ExternalResourcesStateManager:
#     def __init__(self, state: State, index_file_key: str):
#         self.state = state
#         self.index_file_key = index_file_key

#         try:
#             data = self.state[self.index_file_key]
#             states_list = parse_obj_as(list[ExternalResourceState], data)
#             self.index: dict[ExternalResourceKey, ExternalResourceState] = {
#                 item.key: item for item in states_list
#             }
#         except Exception:
#             logging.info("No state file, creating a new one.")
#             self.index = {}

#     def _write_index_file(
#         self,
#     ) -> None:
#         data = [item.dict() for item in self.index.values()]
#         self.state[self.index_file_key] = data

#     def get_external_resource_state(
#         self, key: ExternalResourceKey
#     ) -> ExternalResourceState:
#         obj = self.index.get(
#             key,
#             ExternalResourceState(
#                 key=key,
#                 ts=datetime.now(timezone.utc),
#                 resource_status=ResourceStatus.NOT_EXISTS,
#                 reconciliation=Reconciliation(key=key),
#             ),
#         )
#         return obj

#     def set_external_resource_state(
#         self,
#         key: ExternalResourceKey,
#         state: ExternalResourceState,
#     ) -> None:
#         self.index[key] = state

#     def del_external_resource_state(self, key: ExternalResourceKey) -> None:
#         del self.index[key]

#     def get_all_resource_keys(self) -> list[ExternalResourceKey]:
#         return list[ExternalResourceKey](self.index.keys())

#     def save_state(self) -> None:
#         self._write_index_file()
#         # self._write_external_resource_states()


class DynamoDBStateAdapater:
    KEY_PROVISION_PROVIDER = "key.provision_provider"
    KEY_PROVISIONER_NAME = "key.provisioner_name"
    KEY_PROVIDER = "key.provider"
    KEY_IDENTIFIER = "key.identifier"
    RECONC_RESOURCE_DIGEST = "reconc.resource_digest"
    RECONC_MODCONF_IMAGE = "reconc.modconf.image"
    RECONC_MODCONF_VERSION = "reconc.modconf.version"
    RECONC_MODCONF_DRIFT_MINS = "reconc.modconf.drift_mins"
    RECONC_MODCONF_TIMEOUT_MINS = "reconc.modconf.timeout_mins"
    RECONC_INPUT = "reconc.input"
    RECONC_ACTION = "reconc.action"
    RECONC_ERRORS = "reconciliation_errors"
    RESOURCE_KEY = "resource_key"
    RESOURCE_STATUS = "resource_status"
    RESOURCE_DIGEST = "resource_digest"
    TIMESTAMP = "ts"

    def _get_value(self, item: Mapping[str, Any], key: str, _type: str = "S") -> Any:
        return item[key][_type]

    def _item_has_reconcilitation(self, item: Mapping[str, Any]) -> bool:
        # Just check if one of the reconcilitation attributes exists
        return DynamoDBStateAdapater.RECONC_ACTION in item

    def deserialize(self, item: Mapping[str, Any]) -> ExternalResourceState:
        key = ExternalResourceKey(
            provision_provider=self._get_value(item, self.KEY_PROVISION_PROVIDER),
            provisioner_name=self._get_value(item, self.KEY_PROVISIONER_NAME),
            provider=self._get_value(item, self.KEY_PROVIDER),
            identifier=self._get_value(item, self.KEY_IDENTIFIER),
        )
        if self._item_has_reconcilitation(item):
            r = Reconciliation(
                key=key,
                resource_digest=self._get_value(item, self.RECONC_RESOURCE_DIGEST),
                input=self._get_value(item, self.RECONC_INPUT),
                action=self._get_value(item, self.RECONC_ACTION),
                module_configuration=ExternalResourceModuleConfiguration(
                    image=self._get_value(item, self.RECONC_MODCONF_IMAGE),
                    version=self._get_value(item, self.RECONC_MODCONF_VERSION),
                    reconcile_drift_interval_minutes=self._get_value(
                        item, self.RECONC_MODCONF_DRIFT_MINS, _type="N"
                    ),
                    reconcile_timeout_minutes=self._get_value(
                        item, self.RECONC_MODCONF_TIMEOUT_MINS, _type="N"
                    ),
                ),
            )
        else:
            r = Reconciliation(key=key)
        return ExternalResourceState(
            key=key,
            ts=self._get_value(item, self.TIMESTAMP),
            resource_digest=self._get_value(item, self.RESOURCE_DIGEST),
            resource_status=self._get_value(item, self.RESOURCE_STATUS),
            reconciliation=r,
            reconciliation_errors=int(
                self._get_value(item, self.RECONC_ERRORS, _type="N")
            ),
        )

    def serialize(self, state: ExternalResourceState) -> dict[str, Any]:
        return {
            self.RESOURCE_KEY: {"S": state.key.digest()},
            self.KEY_PROVISION_PROVIDER: {"S": state.key.provision_provider},
            self.KEY_PROVISIONER_NAME: {"S": state.key.provisioner_name},
            self.KEY_PROVIDER: {"S": state.key.provider},
            self.KEY_IDENTIFIER: {"S": state.key.identifier},
            self.TIMESTAMP: {"S": state.ts.isoformat()},
            self.RESOURCE_STATUS: {"S": state.resource_status.value},
            self.RESOURCE_DIGEST: {"S": state.resource_digest},
            self.RECONC_ERRORS: {"N": str(state.reconciliation_errors)},
            self.RECONC_RESOURCE_DIGEST: {"S": state.reconciliation.resource_digest},
            self.RECONC_INPUT: {"S": state.reconciliation.input},
            self.RECONC_ACTION: {"S": state.reconciliation.action.value},
            self.RECONC_MODCONF_IMAGE: {
                "S": state.reconciliation.module_configuration.image
            },
            self.RECONC_MODCONF_VERSION: {
                "S": state.reconciliation.module_configuration.version
            },
            self.RECONC_MODCONF_DRIFT_MINS: {
                "N": str(
                    state.reconciliation.module_configuration.reconcile_drift_interval_minutes
                )
            },
            self.RECONC_MODCONF_TIMEOUT_MINS: {
                "N": str(
                    state.reconciliation.module_configuration.reconcile_timeout_minutes
                )
            },
        }


class ExternalResourcesStateDynamoDB:
    def __init__(self, table_name: str, index_name: str) -> None:
        self.adapter = DynamoDBStateAdapater()
        self.client = boto3.client("dynamodb", region_name="us-east-1")
        self._table = table_name
        self._index_name = index_name
        self.partial_resources = self._get_all_resources_by_index()

    def get_external_resource_state(
        self, key: ExternalResourceKey
    ) -> ExternalResourceState:
        data = self.client.get_item(
            TableName=self._table,
            ConsistentRead=True,
            Key={self.adapter.RESOURCE_KEY: {"S": key.digest()}},
        )
        if "Item" in data:
            return self.adapter.deserialize(data["Item"])
        else:
            return ExternalResourceState(
                key=key,
                ts=datetime.now(timezone.utc),
                resource_status=ResourceStatus.NOT_EXISTS,
                reconciliation=Reconciliation(key=key),
                reconciliation_errors=0,
            )

    def set_external_resource_state(
        self,
        state: ExternalResourceState,
    ) -> None:
        self.client.put_item(TableName=self._table, Item=self.adapter.serialize(state))

    def del_external_resource_state(self, key: ExternalResourceKey) -> None:
        self.client.delete_item(
            TableName=self._table,
            Key={self.adapter.RESOURCE_KEY: {"S": key.digest()}},
        )

    def _get_all_resources_by_index(
        self,
    ) -> dict[ExternalResourceKey, ExternalResourceState]:
        # TODO: Need to implement pagination if this goes further
        # than 1Mb per response
        logging.info("Getting all Resources from DynamoDb")
        partials = {}
        for item in self.client.scan(
            TableName=self._table, IndexName=self._index_name
        ).get("Items", []):
            s = self.adapter.deserialize(item)
            partials[s.key] = s
        return partials

    def get_all_resource_keys(self) -> list[ExternalResourceKey]:
        return [k for k in self.partial_resources.keys()]

    def update_resource_status(
        self, key: ExternalResourceKey, status: ResourceStatus
    ) -> None:
        self.client.update_item(
            TableName=self._table,
            Key={self.adapter.RESOURCE_KEY: {"S": key.digest()}},
            UpdateExpression="set resource_status=:new_value",
            ExpressionAttributeValues={":new_value": {"S": status.value}},
            ReturnValues="UPDATED_NEW",
        )
