from collections.abc import Generator
from typing import TYPE_CHECKING

import boto3
import pytest
from moto import mock_aws

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = object
from pytest import MonkeyPatch
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_state_settings import (
    AppInterfaceStateConfigurationS3V1,
)
from reconcile.gql_definitions.common.state_aws_account import AWSAccountV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.typed_queries.get_state_aws_account import get_state_aws_account
from reconcile.utils import state
from reconcile.utils.secret_reader import (
    ConfigSecretReader,
    SecretReaderBase,
)
from reconcile.utils.state import (
    AbortStateTransactionError,
    S3CredsBasedStateConfiguration,
    S3ProfileBasedStateConfiguration,
    State,
    StateInaccessibleError,
    TransactionStateObj,
    acquire_state_settings,
)

BUCKET = "some-bucket"
ACCOUNT = "some-account"
REGION = "region"
VAULT_SECRET_PATH = "secret/data/path"
VAULT_SECRET_VERSION = "1"
AWS_ACCESS_KEY_ID = "id"
AWS_SECRET_ACCESS_KEY = "key"


@pytest.fixture
def accounts() -> list[dict[str, str]]:
    """Account name is needed to instantiate a State"""
    return [{"name": "some-account"}]


@pytest.fixture
def s3_client(monkeypatch: MonkeyPatch) -> Generator[S3Client, None, None]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", BUCKET)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCOUNT", ACCOUNT)

    with mock_aws():
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket=BUCKET)
        yield s3_client


@pytest.fixture
def integration() -> str:
    return "integration-name"


@pytest.fixture
def integration_state(s3_client: S3Client, integration: str) -> State:
    return State(
        integration=integration,
        bucket=BUCKET,
        client=s3_client,
    )


@pytest.fixture
def all_state(s3_client: S3Client) -> State:
    return State(
        integration="",
        bucket=BUCKET,
        client=s3_client,
    )


class MockAWSCredsSecretReader(SecretReaderBase):
    def _read(
        self, path: str, field: str, format: str | None, version: int | None
    ) -> str:
        return "secret"

    def _read_all(
        self, path: str, field: str, format: str | None, version: int | None
    ) -> dict[str, str]:
        return {
            "aws_access_key_id": AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
        }


def test_ls_returns_correct_file(integration_state: State, s3_client: S3Client) -> None:
    s3_client.put_object(
        Bucket=integration_state.bucket,
        Key="state/integration-name/some-file-1",
        Body="test",
    )
    # Creating some-file-2 to identify when two or more integrations have similar names
    s3_client.put_object(
        Bucket=integration_state.bucket,
        Key="state/integration-name-2/some-file-2",
        Body="test",
    )

    keys = integration_state.ls()
    assert keys == ["/some-file-1"]


def test_ls_when_integration_is_empty_string(
    all_state: State, s3_client: S3Client
) -> None:
    s3_client.put_object(
        Bucket=all_state.bucket, Key="state/integration-name-1/some-file-1", Body="test"
    )
    s3_client.put_object(
        Bucket=all_state.bucket, Key="state/integration-name-2/some-file-2", Body="test"
    )
    s3_client.put_object(
        Bucket=all_state.bucket,
        Key="state/integration-name-3/nested/some-file-2",
        Body="test",
    )

    keys = all_state.ls()

    expected = [
        "/integration-name-1/some-file-1",
        "/integration-name-2/some-file-2",
        "/integration-name-3/nested/some-file-2",
    ]
    assert keys == expected


def test_ls_when_state_is_empty(integration_state: State, s3_client: S3Client) -> None:
    keys = integration_state.ls()

    assert keys == []


def test_ls_when_that_are_more_than_1000_keys(
    integration_state: State, s3_client: S3Client
) -> None:
    expected = []
    # Putting more than 1000 keys
    for i in range(0, 1010):
        key = f"/some-file-{i}"
        expected.append(key)

        s3_client.put_object(
            Bucket=integration_state.bucket,
            Key=f"state/integration-name{key}",
            Body=f"{i}",
        )

    # S3 response is sorted
    expected.sort()

    keys = integration_state.ls()

    assert keys == expected


def test_exists_for_existing_key(integration_state: State, s3_client: S3Client) -> None:
    key = "some-key"

    s3_client.put_object(
        Bucket=integration_state.bucket,
        Key=f"state/integration-name/{key}",
        Body="test",
    )
    assert integration_state.exists(key)


def test_exists_for_missing_key(integration_state: State) -> None:
    assert not integration_state.exists("some-key")


def test_exists_for_missing_bucket(s3_client: S3Client) -> None:
    with pytest.raises(StateInaccessibleError, match=r".*404.*"):
        State(
            integration="",
            bucket="does-not-exist",
            client=s3_client,
        )


def test_add_without_metadata(integration_state: State) -> None:
    integration_state.add("k", "v", force=True)

    assert integration_state.head("k") == (True, {})
    assert integration_state.get("k") == "v"


def test_add_with_metadata(integration_state: State) -> None:
    metadata = {"a": "b"}

    integration_state.add("k", "v", metadata=metadata, force=True)

    assert integration_state.head("k") == (True, metadata)
    assert integration_state.get("k") == "v"


#
# aquire settings
#


def test_acquire_state_settings_env_vault(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", BUCKET)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_REGION", REGION)
    monkeypatch.setenv("APP_INTERFACE_STATE_VAULT_SECRET", VAULT_SECRET_PATH)

    state_settings = acquire_state_settings(secret_reader=MockAWSCredsSecretReader())
    assert state_settings.bucket == BUCKET
    assert state_settings.region == REGION
    assert isinstance(state_settings, S3CredsBasedStateConfiguration)
    assert state_settings.access_key_id == AWS_ACCESS_KEY_ID
    assert state_settings.secret_access_key == AWS_SECRET_ACCESS_KEY


def test_acquire_state_settings_env_account(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", BUCKET)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCOUNT", ACCOUNT)

    state_settings = acquire_state_settings(
        secret_reader=MockAWSCredsSecretReader(),
        query_func=lambda gql_query, **kwargs: {
            "accounts": [
                {
                    "name": ACCOUNT,
                    "resourcesDefaultRegion": REGION,
                    "automationToken": {
                        "path": VAULT_SECRET_PATH,
                        "field": "all",
                        "version": None,
                        "format": None,
                    },
                }
            ]
        },
    )
    assert state_settings.bucket == BUCKET
    assert state_settings.region == REGION
    assert isinstance(state_settings, S3CredsBasedStateConfiguration)
    assert state_settings.access_key_id == AWS_ACCESS_KEY_ID
    assert state_settings.secret_access_key == AWS_SECRET_ACCESS_KEY


def test_acquire_state_settings_env_missing_account(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", BUCKET)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCOUNT", ACCOUNT)

    with pytest.raises(StateInaccessibleError):
        acquire_state_settings(
            secret_reader=ConfigSecretReader(),
            query_func=lambda gql_query, **kwargs: {"accounts": None},
        )


def test_acquire_state_settings_env_creds(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", BUCKET)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_REGION", REGION)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_ACCESS_KEY_ID", AWS_ACCESS_KEY_ID)
    monkeypatch.setenv(
        "APP_INTERFACE_STATE_BUCKET_SECRET_ACCESS_KEY", AWS_SECRET_ACCESS_KEY
    )

    state_settings = acquire_state_settings(secret_reader=MockAWSCredsSecretReader())
    assert state_settings.bucket == BUCKET
    assert state_settings.region == REGION
    assert isinstance(state_settings, S3CredsBasedStateConfiguration)
    assert state_settings.access_key_id == AWS_ACCESS_KEY_ID
    assert state_settings.secret_access_key == AWS_SECRET_ACCESS_KEY


def test_acquire_state_settings_env_profile(
    mocker: MockerFixture, monkeypatch: MonkeyPatch
) -> None:
    get_aws_account_by_name_mock = mocker.patch.object(
        state, "aws_config_file_path", autospec=True
    )
    get_aws_account_by_name_mock.return_value = "/some/path/to/a/config/file"

    profile = "profile"
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET", BUCKET)
    monkeypatch.setenv("APP_INTERFACE_STATE_BUCKET_REGION", REGION)
    monkeypatch.setenv("APP_INTERFACE_STATE_AWS_PROFILE", "profile")

    state_settings = acquire_state_settings(secret_reader=MockAWSCredsSecretReader())
    assert state_settings.bucket == BUCKET
    assert state_settings.region == REGION
    assert isinstance(state_settings, S3ProfileBasedStateConfiguration)
    assert state_settings.profile == profile


def test_acquire_state_settings_ai_settings(mocker: MockerFixture) -> None:
    get_aws_account_by_name_mock = mocker.patch.object(
        state, "get_app_interface_state_settings", autospec=True
    )
    get_aws_account_by_name_mock.return_value = AppInterfaceStateConfigurationS3V1(
        provider="s3",
        bucket=BUCKET,
        region=REGION,
        credentials=VaultSecret(
            path=VAULT_SECRET_PATH,
            field="all",
            format=None,
            version=None,
        ),
    )

    state_settings = acquire_state_settings(secret_reader=MockAWSCredsSecretReader())
    assert state_settings.bucket == BUCKET
    assert state_settings.region == REGION
    assert isinstance(state_settings, S3CredsBasedStateConfiguration)
    assert state_settings.access_key_id == AWS_ACCESS_KEY_ID
    assert state_settings.secret_access_key == AWS_SECRET_ACCESS_KEY


def test_acquire_state_settings_no_settings(mocker: MockerFixture) -> None:
    get_aws_account_by_name_mock = mocker.patch.object(
        state, "get_app_interface_state_settings", autospec=True
    )
    get_aws_account_by_name_mock.return_value = None

    with pytest.raises(StateInaccessibleError):
        acquire_state_settings(secret_reader=MockAWSCredsSecretReader())


def test_state_get_aws_account_by_name() -> None:
    # account not found
    assert (
        get_state_aws_account(
            "some-account", query_func=lambda gql_query, **kwargs: {"accounts": None}
        )
        is None
    )
    account = get_state_aws_account(
        "some-account",
        query_func=lambda gql_query, **kwargs: {
            "accounts": [
                {
                    "name": kwargs["variables"]["name"],
                    "resourcesDefaultRegion": "REGION",
                    "automationToken": {
                        "path": "VAULT_SECRET_PATH",
                        "field": "all",
                        "version": None,
                        "format": None,
                    },
                }
            ]
        },
    )
    assert isinstance(account, AWSAccountV1)
    assert account.name == "some-account"


def test_state_transaction_key_exists(
    integration_state: State, integration: str, s3_client: S3Client
) -> None:
    s3_client.put_object(
        Bucket=integration_state.bucket,
        Key=f"state/{integration}/feature.foo.bar",
        Body='"set"',
    )

    assert integration_state["feature.foo.bar"] == "set"
    with integration_state.transaction("feature.foo.bar", "set") as state:
        assert state.exists


def test_state_transaction_value_via_transaction(integration_state: State) -> None:
    with integration_state.transaction("feature.foo.bar", "set") as state:
        assert not state.exists
    assert integration_state["feature.foo.bar"] == "set"


def test_state_transaction_value_via_state_obj(integration_state: State) -> None:
    with integration_state.transaction("feature.foo.bar") as state:
        state.value = "set"
        assert not state.exists
        # here should be the code that acts now
    # and then the state should be updated
    assert integration_state["feature.foo.bar"] == "set"


def test_state_transaction_value_via_both(integration_state: State) -> None:
    with integration_state.transaction("feature.foo.bar", "foo") as state:
        state.value = "bar"
        assert not state.exists
    assert integration_state["feature.foo.bar"] == "bar"


def test_state_transaction_no_value(integration_state: State) -> None:
    with integration_state.transaction("feature.foo.bar") as state:
        assert not state.exists

    with pytest.raises(KeyError):
        integration_state["feature.foo.bar"]


def test_state_transaction_key_exists_value_via_transaction(
    integration_state: State, integration: str, s3_client: S3Client
) -> None:
    s3_client.put_object(
        Bucket=integration_state.bucket,
        Key=f"state/{integration}/feature.foo.bar",
        Body='"set"',
    )

    assert integration_state["feature.foo.bar"] == "set"
    with integration_state.transaction("feature.foo.bar", "changed") as state:
        assert state.value == "set"
    assert integration_state["feature.foo.bar"] == "changed"


def test_state_transaction_key_exists_value_via_state_obj(
    integration_state: State, integration: str, s3_client: S3Client
) -> None:
    s3_client.put_object(
        Bucket=integration_state.bucket,
        Key=f"state/{integration}/feature.foo.bar",
        Body='"set"',
    )

    assert integration_state["feature.foo.bar"] == "set"
    with integration_state.transaction("feature.foo.bar") as state:
        assert state.value == "set"
        state.value = "changed"
    assert integration_state["feature.foo.bar"] == "changed"


def test_state_transaction_noop_if_no_value_in_transaction(
    integration_state: State, integration: str, s3_client: S3Client
) -> None:
    s3_client.put_object(
        Bucket=integration_state.bucket,
        Key=f"state/{integration}/feature.foo.bar",
        Body='"set"',
    )

    assert integration_state["feature.foo.bar"] == "set"
    with integration_state.transaction("feature.foo.bar") as state:
        assert state.value == "set"
    assert integration_state["feature.foo.bar"] == "set"


def test_state_transaction_exception(
    integration_state: State, integration: str, s3_client: S3Client
) -> None:
    try:
        with integration_state.transaction("feature.foo.bar", "set") as state:
            assert not state.exists
            raise FileNotFoundError("Some error")
    except FileNotFoundError:
        with pytest.raises(KeyError):
            integration_state["feature.foo.bar"]
    else:
        raise AssertionError("The exception was not raised")


def test_state_transaction_abort(
    integration_state: State, integration: str, s3_client: S3Client
) -> None:
    with integration_state.transaction("feature.foo.bar", "set") as state:
        assert not state.exists
        raise AbortStateTransactionError("We want to abort the transaction")

    with pytest.raises(KeyError):
        integration_state["feature.foo.bar"]


def test_state_transaction_state_obj_nothing_set() -> None:
    # nothing set yet
    obj = TransactionStateObj(key="key")
    assert obj.value is None
    assert not obj.changed
    assert not obj.exists

    obj.value = "value"
    assert obj.value == "value"
    assert obj.changed
    assert not obj.exists


def test_state_transaction_state_obj_init_value() -> None:
    # init value but no current one
    obj = TransactionStateObj(key="key", value="value")
    assert obj.value == "value"
    assert not obj.changed
    assert obj.exists

    obj.value = "another-value"
    assert obj.value == "another-value"
    assert obj.changed
    assert obj.exists


def test_state_transaction_state_obj_bool() -> None:
    # init value but no current one
    obj = TransactionStateObj(key="key", value=True)
    assert obj.value is True
    obj.value = False
    assert obj.value is False
    assert obj.changed
    assert obj.exists
