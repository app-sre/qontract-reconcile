import boto3
import pytest
from botocore.errorfactory import ClientError
from moto import mock_s3

from reconcile.gql_definitions.common.app_interface_state_settings import (
    AppInterfaceStateConfigurationS3V1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.secret_reader import ConfigSecretReader
from reconcile.utils.state import (
    StateInaccessibleException,
    _init_state_from_accounts,
    _init_state_from_settings,
)

BUCKET = "some-bucket"
ACCOUNT = "some-account"


@pytest.fixture
def accounts():
    """Account name is needed to instantiate a State"""
    return [{"name": "some-account"}]


@pytest.fixture
def s3_client(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", BUCKET)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCOUNT", ACCOUNT)

    with mock_s3():
        s3_client = boto3.client("s3", region_name="us-east-1")
        yield s3_client


def test_ls_returns_correct_file(accounts, s3_client, mocker):
    s3_client.create_bucket(Bucket="some-bucket")
    s3_client.put_object(
        Bucket="some-bucket", Key="state/integration-name/some-file-1", Body="test"
    )

    # Creating some-file-2 to identify when two or more integrations have
    # similar names
    s3_client.put_object(
        Bucket="some-bucket", Key="state/integration-name-2/some-file-2", Body="test"
    )

    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    state = _init_state_from_accounts(
        integration="integration-name",
        bucket_name=BUCKET,
        account_name=ACCOUNT,
        accounts=accounts,
        secret_reader=ConfigSecretReader(),
    )

    keys = state.ls()

    expected = ["/some-file-1"]

    assert keys == expected


def test_ls_when_integration_is_empty_string(accounts, s3_client, mocker):
    s3_client.create_bucket(Bucket="some-bucket")
    s3_client.put_object(
        Bucket="some-bucket", Key="state/integration-name-1/some-file-1", Body="test"
    )
    s3_client.put_object(
        Bucket="some-bucket", Key="state/integration-name-2/some-file-2", Body="test"
    )
    s3_client.put_object(
        Bucket="some-bucket",
        Key="state/integration-name-3/nested/some-file-2",
        Body="test",
    )

    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    state = _init_state_from_accounts(
        integration="",
        bucket_name=BUCKET,
        account_name=ACCOUNT,
        accounts=accounts,
        secret_reader=ConfigSecretReader(),
    )

    keys = state.ls()

    expected = [
        "/integration-name-1/some-file-1",
        "/integration-name-2/some-file-2",
        "/integration-name-3/nested/some-file-2",
    ]

    assert keys == expected


def test_ls_when_state_is_empty(accounts, s3_client, mocker):
    s3_client.create_bucket(Bucket="some-bucket")

    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    state = _init_state_from_accounts(
        integration="integration-name",
        bucket_name=BUCKET,
        account_name=ACCOUNT,
        accounts=accounts,
        secret_reader=ConfigSecretReader(),
    )

    keys = state.ls()

    assert keys == []


def test_ls_when_that_are_more_than_1000_keys(accounts, s3_client, mocker):
    s3_client.create_bucket(Bucket="some-bucket")

    expected = []
    # Putting more than 1000 keys
    for i in range(0, 1010):
        key = f"/some-file-{i}"
        expected.append(key)

        s3_client.put_object(
            Bucket="some-bucket", Key=f"state/integration{key}", Body=f"{i}"
        )

    # S3 response is sorted
    expected.sort()

    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    state = _init_state_from_accounts(
        integration="integration",
        bucket_name=BUCKET,
        account_name=ACCOUNT,
        accounts=accounts,
        secret_reader=ConfigSecretReader(),
    )

    keys = state.ls()

    assert keys == expected


def test_exists_for_existing_key(accounts, s3_client, mocker):
    key = "some-key"

    s3_client.create_bucket(Bucket="some-bucket")
    s3_client.put_object(
        Bucket="some-bucket", Key=f"state/integration-name/{key}", Body="test"
    )

    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    state = _init_state_from_accounts(
        integration="integration-name",
        bucket_name=BUCKET,
        account_name=ACCOUNT,
        accounts=accounts,
        secret_reader=ConfigSecretReader(),
    )
    assert state.exists(key)


def test_exists_for_missing_key(accounts, s3_client, mocker):
    s3_client.create_bucket(Bucket="some-bucket")

    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    state = _init_state_from_accounts(
        integration="integration-name",
        bucket_name=BUCKET,
        account_name=ACCOUNT,
        accounts=accounts,
        secret_reader=ConfigSecretReader(),
    )
    assert not state.exists("some-key")


def test_exists_for_missing_bucket(accounts, s3_client, mocker):
    # don't create a bucket unlink in all the other tests
    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    with pytest.raises(StateInaccessibleException, match=r".*404.*"):
        _init_state_from_accounts(
            integration="integration-name",
            bucket_name=BUCKET,
            account_name=ACCOUNT,
            accounts=accounts,
            secret_reader=ConfigSecretReader(),
        )


def test_exists_for_forbidden(accounts, s3_client, mocker):
    forbidden_error = ClientError({"Error": {"Code": "403"}}, None)
    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value.head_object.side_effect = (
        forbidden_error
    )

    state = _init_state_from_accounts(
        integration="integration-name",
        bucket_name=BUCKET,
        account_name=ACCOUNT,
        accounts=accounts,
        secret_reader=ConfigSecretReader(),
    )

    with pytest.raises(StateInaccessibleException, match=r".*403.*"):
        state.exists("some-key")


#
# init state from settings
#


def test__init_state_from_settings(accounts, s3_client, mocker):
    s3_client.create_bucket(Bucket=BUCKET)

    mock_aws_api = mocker.patch("reconcile.utils.state.AWSApi", autospec=True)
    mock_aws_api.return_value.get_session_client.return_value = s3_client

    state = _init_state_from_settings(
        integration="",
        secret_reader=ConfigSecretReader(),
        state_settings=AppInterfaceStateConfigurationS3V1(
            provider="s3",
            bucket=BUCKET,
            region="us-east-1",
            credentials=VaultSecret(
                path="secret/data/path",
                field="all",
                format=None,
                version=None,
            ),
        ),
    )

    assert state
