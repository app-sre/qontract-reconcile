from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from qontract_utils.aws_api_typed._hooks import AWSApiCallContext
from qontract_utils.aws_api_typed.sts import AWSApiSts
from qontract_utils.hooks import Hooks

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from mypy_boto3_sts import STSClient
    from pytest_mock import MockerFixture


@pytest.fixture
def sts_client(mocker: MockerFixture) -> STSClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_sts(sts_client: STSClient) -> AWSApiSts:
    return AWSApiSts(client=sts_client)


def test_aws_api_typed_sts_assume_role(
    aws_api_sts: AWSApiSts, sts_client: MagicMock
) -> None:
    now = datetime.now(tz=UTC)
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
    now = datetime.now(tz=UTC)
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


def test_hooks_fire_on_method_call(sts_client: MagicMock) -> None:
    contexts: list[AWSApiCallContext] = []
    api = AWSApiSts(client=sts_client, hooks=Hooks(pre_hooks=[contexts.append]))
    now = datetime.now(tz=UTC)
    sts_client.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "id",
            "SecretAccessKey": "secret",
            "SessionToken": "token",
            "Expiration": now,
        }
    }
    api.assume_role("123456", "role")
    assert len(contexts) == 1
    assert contexts[0].method == "assume_role"
    assert contexts[0].service == "sts"
