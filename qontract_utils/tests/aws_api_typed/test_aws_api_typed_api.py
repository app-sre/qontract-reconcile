from __future__ import annotations

import pytest
from boto3 import Session
from pytest_mock import MockerFixture
from qontract_utils.aws_api_typed.account import AWSApiAccount
from qontract_utils.aws_api_typed.api import AWSApi, AWSStaticCredentials
from qontract_utils.aws_api_typed.cloudformation import AWSApiCloudFormation
from qontract_utils.aws_api_typed.dynamodb import AWSApiDynamoDB
from qontract_utils.aws_api_typed.iam import AWSApiIam
from qontract_utils.aws_api_typed.logs import AWSApiLogs
from qontract_utils.aws_api_typed.organization import AWSApiOrganizations
from qontract_utils.aws_api_typed.s3 import AWSApiS3
from qontract_utils.aws_api_typed.service_quotas import AWSApiServiceQuotas
from qontract_utils.aws_api_typed.sts import AWSApiSts, AWSCredentials
from qontract_utils.aws_api_typed.support import AWSApiSupport


@pytest.fixture
def aws_api() -> AWSApi:
    return AWSApi(
        AWSStaticCredentials(
            access_key_id="access_key_id",
            secret_access_key="secret_access_key",
            region="us-east-1",
        )
    )


@pytest.mark.parametrize(
    ("region", "partition", "expected_fips"),
    [
        ("us-east-1", "aws", None),
        ("us-gov-west-1", "aws-us-gov", True),
        ("us-gov-east-1", "aws-us-gov", True),
        ("cn-north-1", "aws-cn", None),
    ],
)
def test_aws_api_typed_api_selects_govcloud_fips_internally(
    mocker: MockerFixture, *, region: str, partition: str, expected_fips: bool | None
) -> None:
    """The shared client owns GovCloud policy without changing other partitions."""
    credentials = mocker.Mock(spec=AWSStaticCredentials)
    session = credentials.build_session.return_value
    session.region_name = region
    session.get_partition_for_region.return_value = partition
    client = session.client.return_value
    with AWSApi(credentials) as api:
        assert api.iam.client is client
        config = session.client.call_args.kwargs["config"]
        assert config.use_fips_endpoint is expected_fips
        assert config.retries["mode"] == "standard"
        assert config.retries["total_max_attempts"] == 10
    session.get_partition_for_region.assert_called_once_with(region)
    session.client.return_value.close.assert_called_once()


def test_aws_api_typed_api_init(aws_api: AWSApi) -> None:
    assert isinstance(aws_api.session, Session)
    assert aws_api.session.region_name == "us-east-1"


@pytest.mark.parametrize("region", ["us-gov-west-1", "us-gov-east-1"])
@pytest.mark.parametrize("use_assume_role", [True, False])
def test_govcloud_derived_sessions_keep_internal_fips_policy(
    mocker: MockerFixture, *, region: str, use_assume_role: bool
) -> None:
    """Assumed-role and temporary sessions select FIPS without caller options."""
    sts = mocker.patch.object(AWSApi, "sts")
    credentials = AWSCredentials(
        AccessKeyId="test-access",
        SecretAccessKey="test-secret",
        SessionToken="test-token",
        Expiration="1",
    )
    sts.assume_role.return_value = credentials
    sts.get_session_token.return_value = credentials
    client = mocker.patch("qontract_utils.aws_api_typed.api.Session.client")
    with AWSApi(
        AWSStaticCredentials(
            access_key_id="test-access", secret_access_key="test-secret", region=region
        )
    ) as api:
        derived = (
            api.assume_role("123456789012", "role")
            if use_assume_role
            else api.temporary_session()
        )
        with derived:
            assert isinstance(derived.iam, AWSApiIam)
            assert derived.session.region_name == region
            assert client.call_args.kwargs["config"].use_fips_endpoint is True
    client.return_value.close.assert_called_once()


def test_aws_api_typed_api_context_manager(
    aws_api: AWSApi, mocker: MockerFixture
) -> None:
    client_mock = mocker.MagicMock()
    aws_api._session_clients = [client_mock]
    with aws_api as api:
        assert api == aws_api
    client_mock.close.assert_called_once()
    assert not aws_api._session_clients


def test_aws_api_typed_api_close(aws_api: AWSApi, mocker: MockerFixture) -> None:
    client_mock = mocker.MagicMock()
    aws_api._session_clients = [client_mock]
    aws_api.close()
    client_mock.close.assert_called_once()
    assert not aws_api._session_clients


def test_aws_api_typed_api_account(aws_api: AWSApi) -> None:
    sub_api = aws_api.account
    assert isinstance(sub_api, AWSApiAccount)


def test_aws_api_typed_api_cloudformation(aws_api: AWSApi) -> None:
    sub_api = aws_api.cloudformation
    assert isinstance(sub_api, AWSApiCloudFormation)


def test_aws_api_typed_api_dynamodb(aws_api: AWSApi) -> None:
    sub_api = aws_api.dynamodb
    assert isinstance(sub_api, AWSApiDynamoDB)


def test_aws_api_typed_api_iam(aws_api: AWSApi) -> None:
    sub_api = aws_api.iam
    assert isinstance(sub_api, AWSApiIam)


def test_aws_api_typed_api_logs(aws_api: AWSApi) -> None:
    sub_api = aws_api.logs
    assert isinstance(sub_api, AWSApiLogs)


def test_aws_api_typed_api_organizations(aws_api: AWSApi) -> None:
    sub_api = aws_api.organizations
    assert isinstance(sub_api, AWSApiOrganizations)


def test_aws_api_typed_api_s3(aws_api: AWSApi) -> None:
    sub_api = aws_api.s3
    assert isinstance(sub_api, AWSApiS3)


def test_aws_api_typed_api_service_quotas(aws_api: AWSApi) -> None:
    sub_api = aws_api.service_quotas
    assert isinstance(sub_api, AWSApiServiceQuotas)


def test_aws_api_typed_api_sts(aws_api: AWSApi) -> None:
    sub_api = aws_api.sts
    assert isinstance(sub_api, AWSApiSts)


def test_aws_api_typed_api_support(aws_api: AWSApi) -> None:
    sub_api = aws_api.support
    assert isinstance(sub_api, AWSApiSupport)


def test_aws_api_typed_api_assume_role(aws_api: AWSApi, mocker: MockerFixture) -> None:
    mocker.patch.object(AWSApi, "sts")
    aws_api.sts.assume_role.return_value = AWSCredentials(  # type: ignore[attr-defined]
        AccessKeyId="access_key",
        SecretAccessKey="secret_key",
        SessionToken="session_token",
        Expiration="1",
    )
    new_aws_api = aws_api.assume_role("account_id", "role")
    assert isinstance(new_aws_api, AWSApi)
    aws_api.sts.assume_role.assert_called_once_with(  # type: ignore[attr-defined]
        account_id="account_id", role="role"
    )


def test_aws_api_typed_api_get_temporary_credentials(
    aws_api: AWSApi, mocker: MockerFixture
) -> None:
    mocker.patch.object(AWSApi, "sts")
    aws_api.sts.get_session_token.return_value = AWSCredentials(  # type: ignore[attr-defined]
        AccessKeyId="access_key",
        SecretAccessKey="secret_key",
        SessionToken="session_token",
        Expiration="1",
    )
    new_aws_api = aws_api.temporary_session(duration_seconds=1)
    assert isinstance(new_aws_api, AWSApi)
    aws_api.sts.get_session_token.assert_called_once_with(  # type: ignore[attr-defined]
        duration_seconds=1
    )
