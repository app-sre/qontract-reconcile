import base64
import json

from pytest_mock import MockerFixture

from reconcile.external_resources.secrets_sync import OutputSecretsFormatter
from reconcile.utils.secret_reader import SecretReaderBase


def test_outputs(mocker: MockerFixture) -> None:
    secret_data = {
        "test-01__arn": base64.b64encode(b"an_arn").decode(),
        "test-01__resource_name": base64.b64encode(b"a_resource_name").decode(),
        "debug_output": "Zm9vCg==",
    }

    expected_data = {
        "arn": "an_arn",
        "resource_name": "a_resource_name",
        "debug_output": "foo\n",
    }

    formatter = OutputSecretsFormatter(secret_reader=mocker.Mock())
    formatted_data = formatter.format(secret_data)

    assert formatted_data == expected_data


def test_db_outputs(mocker: MockerFixture) -> None:
    secret_data = {
        "rds-test-01__db_name": base64.b64encode(b"postgres").decode(),
        "rds-test-01__db_host": base64.b64encode(b"rds_url").decode(),
        "rds_test-01__engine_version": base64.b64encode(b"15.7").decode(),
    }

    expected_data = {
        "db.name": "postgres",
        "db.host": "rds_url",
        "engine_version": "15.7",
    }

    formatter = OutputSecretsFormatter(secret_reader=mocker.Mock())
    formatted_data = formatter.format(secret_data)

    assert formatted_data == expected_data


def test_vault_ref_output(mocker: MockerFixture) -> None:
    vault_secret = {
        "path": "app-interface/global/rds-ca-cert",
        "field": "us-east-1",
        "version": 2,
    }
    secret_data = {
        "rds-test-01__ca_cert": base64.b64encode(
            f"__vault__:{json.dumps(vault_secret)}".encode()
        ).decode(),
    }
    expected_data = {
        "ca_cert": "secret_data",
    }

    mock_secret_reader = mocker.MagicMock(spec=SecretReaderBase)
    mock_secret_reader.read_secret.return_value = "secret_data"

    formatter = OutputSecretsFormatter(secret_reader=mock_secret_reader)
    formatted_data = formatter.format(secret_data)
    assert formatted_data == expected_data
