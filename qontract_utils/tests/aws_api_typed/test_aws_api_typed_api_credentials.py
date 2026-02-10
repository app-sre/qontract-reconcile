import pytest

from qontract_utils.aws_api_typed.api import (
    AWSStaticCredentials,
    AWSTemporaryCredentials,
)


@pytest.fixture
def aws_static_credentials() -> AWSStaticCredentials:
    return AWSStaticCredentials(
        access_key_id="access-key-id",
        secret_access_key="secret-access-key",
        region="us-east-1",
    )


def test_static_credentials_as_env_vars(
    aws_static_credentials: AWSStaticCredentials,
) -> None:
    assert aws_static_credentials.as_env_vars() == {
        "AWS_ACCESS_KEY_ID": aws_static_credentials.access_key_id,
        "AWS_SECRET_ACCESS_KEY": aws_static_credentials.secret_access_key,
        "AWS_REGION": aws_static_credentials.region,
    }


@pytest.mark.parametrize(
    "profile_name",
    [
        "default",
        "some-profile",
    ],
)
def test_static_credentials_as_file(
    profile_name: str, aws_static_credentials: AWSStaticCredentials
) -> None:
    expected_file = f"""[{profile_name}]\naws_access_key_id = {aws_static_credentials.access_key_id}\naws_secret_access_key = {aws_static_credentials.secret_access_key}\nregion = {aws_static_credentials.region}\n"""
    creds_file = aws_static_credentials.as_credentials_file(profile_name=profile_name)
    assert creds_file == expected_file


@pytest.fixture
def aws_temporary_credentials() -> AWSTemporaryCredentials:
    return AWSTemporaryCredentials(
        access_key_id="access-key-id",
        secret_access_key="secret-access-key",
        session_token="session-token",
        region="us-east-1",
    )


def test_temporary_credentials_as_env_vars(
    aws_temporary_credentials: AWSTemporaryCredentials,
) -> None:
    assert aws_temporary_credentials.as_env_vars() == {
        "AWS_ACCESS_KEY_ID": aws_temporary_credentials.access_key_id,
        "AWS_SECRET_ACCESS_KEY": aws_temporary_credentials.secret_access_key,
        "AWS_SESSION_TOKEN": aws_temporary_credentials.session_token,
        "AWS_REGION": aws_temporary_credentials.region,
    }


@pytest.mark.parametrize(
    "profile_name",
    [
        "default",
        "some-profile",
    ],
)
def test_temporary_credentials_as_file(
    profile_name: str, aws_temporary_credentials: AWSTemporaryCredentials
) -> None:
    expected_file = f"""[{profile_name}]\naws_access_key_id = {aws_temporary_credentials.access_key_id}\naws_secret_access_key = {aws_temporary_credentials.secret_access_key}\naws_session_token = {aws_temporary_credentials.session_token}\nregion = {aws_temporary_credentials.region}\n"""
    creds_file = aws_temporary_credentials.as_credentials_file(
        profile_name=profile_name
    )
    assert creds_file == expected_file
