from datetime import datetime
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.aws_api_typed.sts import AWSApiSts

if TYPE_CHECKING:
    from mypy_boto3_sts import STSClient
else:
    STSClient = object


@pytest.fixture
def sts_client(mocker: MockerFixture) -> STSClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_sts(sts_client: STSClient) -> AWSApiSts:
    return AWSApiSts(client=sts_client)


def test_aws_api_typed_sts_assume_role(
    aws_api_sts: AWSApiSts, sts_client: MagicMock
) -> None:
    now = datetime.now()
    sts_client.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "access_key_id",
            "SecretAccessKey": "secret_access_key",
            "SessionToken": "session_token",
            "Expiration": now,
        }
    }
    credentials = aws_api_sts.assume_role("account_id", "role")
    assert credentials.access_key_id == "access_key_id"
    assert credentials.secret_access_key == "secret_access_key"
    assert credentials.session_token == "session_token"
    assert credentials.expiration == now


def test_aws_api_typed_sts_get_session_token(
    aws_api_sts: AWSApiSts, sts_client: MagicMock
) -> None:
    now = datetime.now()
    sts_client.get_session_token.return_value = {
        "Credentials": {
            "AccessKeyId": "access_key_id",
            "SecretAccessKey": "secret_access_key",
            "SessionToken": "session_token",
            "Expiration": now,
        }
    }
    credentials = aws_api_sts.get_session_token()
    assert credentials.access_key_id == "access_key_id"
    assert credentials.secret_access_key == "secret_access_key"
    assert credentials.session_token == "session_token"
    assert credentials.expiration == now
