from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import botocore
import pytest
from mypy_boto3_iam import IAMClient
from mypy_boto3_iam.type_defs import ListAccountAliasesResponseTypeDef
from pytest_mock import MockerFixture
from qontract_utils.aws_api_typed.iam import AWSApiIam
from qontract_utils.hooks import Hooks

if TYPE_CHECKING:
    from qontract_utils.aws_api_typed._hooks import AWSApiCallContext


@pytest.fixture
def iam_client(mocker: MockerFixture) -> IAMClient:
    return mocker.MagicMock(spec=IAMClient)


@pytest.fixture
def aws_api_iam(iam_client: IAMClient) -> AWSApiIam:
    return AWSApiIam(client=iam_client)


def test_aws_api_typed_iam_create_access_key(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.create_access_key.return_value = {
        "AccessKey": {
            "AccessKeyId": "access_key_id",
            "SecretAccessKey": "secret_access_key",
        }
    }
    access_key = aws_api_iam.create_access_key("user")
    assert access_key.access_key_id == "access_key_id"
    assert access_key.secret_access_key == "secret_access_key"


def test_aws_api_typed_iam_create_user(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.create_user.return_value = {
        "User": {
            "UserName": "user_name",
            "UserId": "user_id",
            "Arn": "arn",
            "Path": "path",
        }
    }
    user = aws_api_iam.create_user("user_name")
    assert user.user_name == "user_name"
    assert user.user_id == "user_id"
    assert user.arn == "arn"
    assert user.path == "path"


def test_aws_api_typed_iam_attach_user_policy(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    aws_api_iam.attach_user_policy("user_name", "policy_arn")
    iam_client.attach_user_policy.assert_called_once_with(
        UserName="user_name",
        PolicyArn="policy_arn",
    )


def test_aws_api_typed_iam_set_account_alias(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    aws_api_iam.set_account_alias("account_alias")
    iam_client.create_account_alias.assert_called_once_with(
        AccountAlias="account_alias",
    )


def test_aws_api_typed_iam_set_account_alias_already_set(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.create_account_alias.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {
                "Code": "EntityAlreadyExists",
                "Message": "An account alias already exists for this account.",
            }
        },
        operation_name="CreateAccountAlias",
    )
    iam_client.list_account_aliases.return_value = ListAccountAliasesResponseTypeDef(
        AccountAliases=["account_alias"],
        IsTruncated=False,
        Marker="",
        ResponseMetadata={
            "RequestId": "request_id",
            "HTTPStatusCode": 200,
            "HTTPHeaders": {},
            "RetryAttempts": 0,
        },
    )
    aws_api_iam.set_account_alias("account_alias")


def test_aws_api_typed_iam_set_account_alias_permission_denied_by_already_set(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.create_account_alias.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "User: arn:aws:iam::xxxxx:user/terraform is not authorized to perform: iam:CreateAccountAlias on resource: * with an explicit deny in a service control policy",
            }
        },
        operation_name="CreateAccountAlias",
    )
    iam_client.list_account_aliases.return_value = ListAccountAliasesResponseTypeDef(
        AccountAliases=["account_alias"],
        IsTruncated=False,
        Marker="",
        ResponseMetadata={
            "RequestId": "request_id",
            "HTTPStatusCode": 200,
            "HTTPHeaders": {},
            "RetryAttempts": 0,
        },
    )
    aws_api_iam.set_account_alias("account_alias")


def test_aws_api_typed_iam_set_account_alias_permission_denied_and_not_set(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.create_account_alias.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "User: arn:aws:iam::xxxxx:user/terraform is not authorized to perform: iam:CreateAccountAlias on resource: * with an explicit deny in a service control policy",
            }
        },
        operation_name="CreateAccountAlias",
    )
    iam_client.list_account_aliases.return_value = ListAccountAliasesResponseTypeDef(
        AccountAliases=["some_other_alias"],
        IsTruncated=False,
        Marker="",
        ResponseMetadata={
            "RequestId": "request_id",
            "HTTPStatusCode": 200,
            "HTTPHeaders": {},
            "RetryAttempts": 0,
        },
    )
    with pytest.raises(botocore.exceptions.ClientError):
        aws_api_iam.set_account_alias("account_alias")


def test_aws_api_typed_iam_get_account_alias(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.list_account_aliases.return_value = {"AccountAliases": ["account_alias"]}
    assert aws_api_iam.get_account_alias() == "account_alias"


def test_aws_api_typed_iam_has_service_linked_role_exists(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.get_role.return_value = {
        "Role": {"RoleName": "AWSServiceRoleForElasticLoadBalancing"}
    }
    assert (
        aws_api_iam.has_service_linked_role("AWSServiceRoleForElasticLoadBalancing")
        is True
    )
    iam_client.get_role.assert_called_once_with(
        RoleName="AWSServiceRoleForElasticLoadBalancing"
    )


def test_aws_api_typed_iam_has_service_linked_role_not_exists(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.get_role.side_effect = botocore.exceptions.ClientError(
        error_response={"Error": {"Code": "NoSuchEntity", "Message": "Role not found"}},
        operation_name="GetRole",
    )
    assert (
        aws_api_iam.has_service_linked_role("AWSServiceRoleForElasticLoadBalancing")
        is False
    )


def test_aws_api_typed_iam_has_service_linked_role_reraises_unexpected_error(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.get_role.side_effect = botocore.exceptions.ClientError(
        error_response={"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
        operation_name="GetRole",
    )
    with pytest.raises(botocore.exceptions.ClientError):
        aws_api_iam.has_service_linked_role("AWSServiceRoleForElasticLoadBalancing")


def test_aws_api_typed_iam_create_service_linked_role(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    aws_api_iam.create_service_linked_role("elasticloadbalancing.amazonaws.com")
    iam_client.create_service_linked_role.assert_called_once_with(
        AWSServiceName="elasticloadbalancing.amazonaws.com"
    )


def test_aws_api_typed_iam_create_service_linked_role_already_exists_concurrent(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.create_service_linked_role.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {
                "Code": "InvalidInput",
                "Message": "Service role name AWSServiceRoleForElasticLoadBalancing has been taken in this account, please try a different suffix.",
            }
        },
        operation_name="CreateServiceLinkedRole",
    )
    aws_api_iam.create_service_linked_role("elasticloadbalancing.amazonaws.com")


def test_aws_api_typed_iam_create_service_linked_role_reraises_unexpected_error(
    aws_api_iam: AWSApiIam, iam_client: MagicMock
) -> None:
    iam_client.create_service_linked_role.side_effect = botocore.exceptions.ClientError(
        error_response={
            "Error": {"Code": "InvalidInput", "Message": "Service is not supported."}
        },
        operation_name="CreateServiceLinkedRole",
    )
    with pytest.raises(botocore.exceptions.ClientError):
        aws_api_iam.create_service_linked_role("unsupported.amazonaws.com")


def test_hooks_fire_on_method_call(iam_client: MagicMock) -> None:
    contexts: list[AWSApiCallContext] = []
    api = AWSApiIam(client=iam_client, hooks=Hooks(pre_hooks=[contexts.append]))
    iam_client.create_access_key.return_value = {
        "AccessKey": {"AccessKeyId": "id", "SecretAccessKey": "secret"}
    }
    api.create_access_key("user")
    assert len(contexts) == 1
    assert contexts[0].method == "create_access_key"
    assert contexts[0].service == "iam"
