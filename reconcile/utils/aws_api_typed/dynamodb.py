from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
else:
    DynamoDBClient = object


class AWSApiDynamoDB:
    def __init__(self, client: DynamoDBClient) -> None:
        self.client = client

    @property
    def boto3_client(self) -> DynamoDBClient:
        """Gets the RAW boto3 DynamoDB client"""
        return self.client

    # def get_item(
    #     self,
    #     table_name: str,
    #     key: Mapping[str, UniversalAttributeValueTypeDef],
    #     attributes_to_get: Sequence[str] | None = None,
    #     consistent_read: bool | None = None,
    #     return_consumed_capacity_type: ReturnConsumedCapacityType | None = None,
    #     projection_expression: str | None = None,
    #     expression_attribute_names: Mapping[str, str] | None = None,
    # ) -> GetItemOutputTypeDef:
    #     _kwargs: dict[str, Any] = {"TableName": table_name, "Key": key}
    #     if attributes_to_get:
    #         _kwargs["AttributesToGet"] = attributes_to_get
    #     if consistent_read:
    #         _kwargs["ConsistentRead"] = consistent_read
    #     if return_consumed_capacity_type:
    #         _kwargs["ReturnConsumedCapacity"] = return_consumed_capacity_type
    #     if projection_expression:
    #         _kwargs["ProjectionExpression"] = projection_expression
    #     if expression_attribute_names:
    #         _kwargs["ExpressionAttributeNames"] = expression_attribute_names

    #     return self.client.get_item(**_kwargs)


#    def delete_item(self) -> None:
# *,
# TableName: str,
# Key: Mapping[str, UniversalAttributeValueTypeDef],
# Expected: Mapping[str, ExpectedAttributeValueTypeDef] = ...,
# ConditionalOperator: ConditionalOperatorType = ...,
# ReturnValues: ReturnValueType = ...,
# ReturnConsumedCapacity: ReturnConsumedCapacityType = ...,
# ReturnItemCollectionMetrics: ReturnItemCollectionMetricsType = ...,
# ConditionExpression: str = ...,
# ExpressionAttributeNames: Mapping[str, str] = ...,
# ExpressionAttributeValues: Mapping[str, UniversalAttributeValueTypeDef] = ...,
# ReturnValuesOnConditionCheckFailure: ReturnValuesOnConditionCheckFailureType = ...,
