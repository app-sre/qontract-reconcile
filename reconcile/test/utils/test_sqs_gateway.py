from unittest.mock import create_autospec

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.sqs_gateway import SQSGateway


@pytest.fixture
def aws_account() -> dict:
    return {
        "uid": "123",
        "name": "my-account",
    }


def test_receive_messages(
    mocker: MockerFixture,
    aws_account: dict,
) -> None:
    queue_url = f"https://sqs/{aws_account['uid']}/queue"
    mocked_os = mocker.patch("reconcile.utils.sqs_gateway.os")
    mocked_os.environ.get.return_value = queue_url
    mocked_aws_api = mocker.patch("reconcile.utils.sqs_gateway.AWSApi")
    mocked_sqs = mocked_aws_api.return_value.get_session_client.return_value
    mocked_sqs.receive_message.return_value = {
        "Messages": [
            {
                "ReceiptHandle": "receipt-handle",
                "Body": '{"key": "value"}',
            }
        ]
    }
    sqs_gateway = SQSGateway(
        [aws_account],
        create_autospec(SecretReader),
    )

    messages = sqs_gateway.receive_messages()
    expected_messages = [("receipt-handle", {"key": "value"})]

    assert messages == expected_messages
    mocked_sqs.receive_message.assert_called_once_with(
        QueueUrl=queue_url,
        VisibilityTimeout=30,
        WaitTimeSeconds=20,
    )
