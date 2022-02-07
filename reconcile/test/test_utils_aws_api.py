import pytest
import boto3
from moto import mock_iam
from reconcile.utils.aws_api import AWSApi


@pytest.fixture
def accounts():
    return [
        {
            'name': 'some-account',
            'automationToken': {
                'path': 'path',
            }
        }
    ]


@pytest.fixture
def aws_api(accounts, mocker):
    mock_secret_reader = mocker.patch(
        'reconcile.utils.aws_api.SecretReader', autospec=True)
    mock_secret_reader.return_value.read_all.return_value = {
        'aws_access_key_id': 'key_id',
        'aws_secret_access_key': 'access_key',
        'region': 'region',
    }
    return AWSApi(1, accounts, init_users=False)


@pytest.fixture
def iam_client():
    with mock_iam():
        iam_client = boto3.client('iam')
        yield iam_client


def test_get_user_key_list(aws_api, iam_client):
    iam_client.create_user(UserName='user')
    iam_client.create_access_key(UserName='user')
    key_list = aws_api._get_user_key_list(iam_client, 'user')
    assert key_list != []


def test_get_user_key_list_empty(aws_api, iam_client):
    iam_client.create_user(UserName='user')
    key_list = aws_api._get_user_key_list(iam_client, 'user')
    assert key_list == []


def test_get_user_key_list_missing_user(aws_api, iam_client):
    iam_client.create_user(UserName='user1')
    key_list = aws_api._get_user_key_list(iam_client, 'user2')
    assert key_list == []


def test_get_user_keys(aws_api, iam_client):
    iam_client.create_user(UserName='user')
    iam_client.create_access_key(UserName='user')
    keys = aws_api.get_user_keys(iam_client, 'user')
    assert keys != []


def test_get_user_keys_empty(aws_api, iam_client):
    iam_client.create_user(UserName='user')
    keys = aws_api.get_user_keys(iam_client, 'user')
    assert keys == []


def test_get_user_key_status(aws_api, iam_client):
    iam_client.create_user(UserName='user')
    iam_client.create_access_key(UserName='user')
    key = aws_api.get_user_keys(iam_client, 'user')[0]
    status = aws_api.get_user_key_status(iam_client, 'user', key)
    assert status == 'Active'
