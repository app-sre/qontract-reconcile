import pytest
import boto3
from moto import mock_s3
from reconcile.utils.state import State


@pytest.fixture
def accounts():
    """Account name is needed to instantiate a State"""
    return [{'name': 'some-account'}]


@mock_s3
def test_ls(accounts, monkeypatch, mocker):
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'testing')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'testing')
    monkeypatch.setenv('AWS_SECURITY_TOKEN', 'testing')
    monkeypatch.setenv('AWS_SESSION_TOKEN', 'testing')
    monkeypatch.setenv('APP_INTERFACE_STATE_BUCKET', 'some-bucket')
    monkeypatch.setenv('APP_INTERFACE_STATE_BUCKET_ACCOUNT', 'some-account')

    s3_client = boto3.client('s3', region_name='us-east-1')
    s3_client.create_bucket(Bucket='some-bucket')

    s3_client.put_object(Bucket='some-bucket',
                         Key='state/integration-name/some-file-1',
                         Body='test')

    # Creating some-file-2 to identify when two or more integrations have
    # similar names
    s3_client.put_object(Bucket='some-bucket',
                         Key='state/integration-name-2/some-file-2',
                         Body='test')

    mock_aws_api = mocker.patch('reconcile.utils.state.AWSApi', autospec=True)
    mock_aws_api.return_value \
        .get_session.return_value \
        .client.return_value = s3_client

    state = State('integration-name', accounts)

    keys = state.ls()

    expected = ['/some-file-1']

    assert keys == expected
