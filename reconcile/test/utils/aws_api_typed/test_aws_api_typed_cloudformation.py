from unittest.mock import MagicMock, call, create_autospec

import pytest
from botocore.exceptions import ClientError
from mypy_boto3_cloudformation import (
    CloudFormationClient,
    StackCreateCompleteWaiter,
    StackUpdateCompleteWaiter,
)
from mypy_boto3_cloudformation.waiter import ChangeSetCreateCompleteWaiter

from reconcile.utils.aws_api_typed.cloudformation import AWSApiCloudFormation


@pytest.fixture
def mock_cloudformation_client() -> MagicMock:
    mock_client = create_autospec(CloudFormationClient)
    mock_client.exceptions.ClientError = ClientError
    return mock_client


def test_init(mock_cloudformation_client: MagicMock) -> None:
    api = AWSApiCloudFormation(mock_cloudformation_client)
    assert api.client == mock_cloudformation_client


@pytest.fixture
def aws_api_cloudformation(
    mock_cloudformation_client: MagicMock,
) -> AWSApiCloudFormation:
    return AWSApiCloudFormation(mock_cloudformation_client)


def test_create_stack(
    mock_cloudformation_client: MagicMock,
    aws_api_cloudformation: AWSApiCloudFormation,
) -> None:
    mock_cloudformation_client.create_change_set.return_value = {
        "Id": "test-change-set-arn",
        "StackId": "test-stack-id",
    }
    mock_change_set_create_complete_waiter = create_autospec(
        ChangeSetCreateCompleteWaiter
    )
    mock_stack_create_complete_waiter = create_autospec(StackCreateCompleteWaiter)
    mock_cloudformation_client.get_waiter.side_effect = [
        mock_change_set_create_complete_waiter,
        mock_stack_create_complete_waiter,
    ]

    result = aws_api_cloudformation.create_stack(
        stack_name="test-stack",
        change_set_name="test-change-set",
        template_body="---\nResources: {}\n",
        parameters={"b": "1", "a": "2"},
        tags={"k2": "v2", "k1": "v1"},
    )

    assert result == "test-stack-id"
    mock_cloudformation_client.create_change_set.assert_called_once_with(
        StackName="test-stack",
        ChangeSetName="test-change-set",
        TemplateBody="---\nResources: {}\n",
        ChangeSetType="CREATE",
        Parameters=[
            {"ParameterKey": "a", "ParameterValue": "2"},
            {"ParameterKey": "b", "ParameterValue": "1"},
        ],
        Tags=[
            {"Key": "k1", "Value": "v1"},
            {"Key": "k2", "Value": "v2"},
        ],
        ImportExistingResources=True,
    )
    mock_cloudformation_client.execute_change_set.assert_called_once_with(
        ChangeSetName="test-change-set-arn"
    )
    mock_cloudformation_client.get_waiter.assert_has_calls([
        call("change_set_create_complete"),
        call("stack_create_complete"),
    ])
    mock_change_set_create_complete_waiter.wait.assert_called_once_with(
        ChangeSetName="test-change-set-arn"
    )
    mock_stack_create_complete_waiter.wait.assert_called_once_with(
        StackName="test-stack"
    )


def test_update_stack(
    mock_cloudformation_client: MagicMock,
    aws_api_cloudformation: AWSApiCloudFormation,
) -> None:
    mock_cloudformation_client.update_stack.return_value = {"StackId": "test-stack-id"}
    mock_stack_create_complete_waiter = create_autospec(StackUpdateCompleteWaiter)
    mock_cloudformation_client.get_waiter.return_value = (
        mock_stack_create_complete_waiter
    )

    result = aws_api_cloudformation.update_stack(
        stack_name="test-stack",
        template_body="---\nResources: {}\n",
        parameters={"b": "1", "a": "2"},
        tags={"k2": "v2", "k1": "v1"},
    )

    assert result == "test-stack-id"
    mock_cloudformation_client.update_stack.assert_called_once_with(
        StackName="test-stack",
        TemplateBody="---\nResources: {}\n",
        Parameters=[
            {"ParameterKey": "a", "ParameterValue": "2"},
            {"ParameterKey": "b", "ParameterValue": "1"},
        ],
        Tags=[
            {"Key": "k1", "Value": "v1"},
            {"Key": "k2", "Value": "v2"},
        ],
    )
    mock_cloudformation_client.get_waiter.assert_called_once_with(
        "stack_update_complete"
    )
    mock_stack_create_complete_waiter.wait.assert_called_once_with(
        StackName="test-stack"
    )


def test_get_stack_exists(
    mock_cloudformation_client: MagicMock,
    aws_api_cloudformation: AWSApiCloudFormation,
) -> None:
    expected_stack = {
        "StackName": "test-stack",
        "StackStatus": "CREATE_COMPLETE",
        "CreationTime": "2023-01-01T00:00:00Z",
    }
    mock_cloudformation_client.describe_stacks.return_value = {
        "Stacks": [expected_stack]
    }

    result = aws_api_cloudformation.get_stack("test-stack")

    assert result == expected_stack
    mock_cloudformation_client.describe_stacks.assert_called_once_with(
        StackName="test-stack"
    )


def test_get_stack_not_found(
    mock_cloudformation_client: MagicMock,
    aws_api_cloudformation: AWSApiCloudFormation,
) -> None:
    mock_cloudformation_client.describe_stacks.side_effect = ClientError(
        error_response={
            "Error": {
                "Code": "ValidationError",
                "Message": "Stack with id non-existent-stack does not exist",
            }
        },
        operation_name="DescribeStacks",
    )

    result = aws_api_cloudformation.get_stack("non-existent-stack")

    assert result is None
    mock_cloudformation_client.describe_stacks.assert_called_once_with(
        StackName="non-existent-stack"
    )


def test_get_template_body_with_yaml(
    mock_cloudformation_client: MagicMock,
    aws_api_cloudformation: AWSApiCloudFormation,
) -> None:
    mock_cloudformation_client.get_template.return_value = {
        "TemplateBody": "---\nResources: {}\n"
    }

    result = aws_api_cloudformation.get_template_body("test-stack")

    assert result == "---\nResources: {}\n"
    mock_cloudformation_client.get_template.assert_called_once_with(
        StackName="test-stack"
    )


def test_get_template_body_with_json(
    mock_cloudformation_client: MagicMock,
    aws_api_cloudformation: AWSApiCloudFormation,
) -> None:
    mock_cloudformation_client.get_template.return_value = {
        "TemplateBody": {"Resources": {}}
    }

    result = aws_api_cloudformation.get_template_body("test-stack")

    assert result == '{"Resources": {}}'
    mock_cloudformation_client.get_template.assert_called_once_with(
        StackName="test-stack"
    )
