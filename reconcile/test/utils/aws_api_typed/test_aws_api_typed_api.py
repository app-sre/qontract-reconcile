import pytest
from boto3 import Session
from pytest_mock import MockerFixture

from reconcile.utils.aws_api_typed.api import AWSApi, AWSStaticCredentials, SubApi
from reconcile.utils.aws_api_typed.iam import AWSApiIam
from reconcile.utils.aws_api_typed.organization import AWSApiOrganizations
from reconcile.utils.aws_api_typed.sts import AWSApiSts, AWSCredentials


@pytest.fixture
def aws_api() -> AWSApi:
    return AWSApi(
        AWSStaticCredentials(
            access_key_id="access_key_id",
            secret_access_key="secret_access_key",
            region="region",
        )
    )


def test_aws_api_typed_api_init(aws_api: AWSApi) -> None:
    assert isinstance(aws_api.session, Session)
    assert aws_api.session.region_name == "region"


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


@pytest.mark.parametrize(
    "api_cls, client_name",
    [
        (AWSApiIam, "iam"),
        (AWSApiOrganizations, "organizations"),
        (AWSApiSts, "sts"),
        pytest.param(
            object,
            "unknown",
            marks=pytest.mark.xfail(strict=True, raises=ValueError),
        ),
    ],
)
def test_aws_api_typed_api_init_sub_api(
    aws_api: AWSApi, mocker: MockerFixture, api_cls: type[SubApi], client_name: str
) -> None:
    session_mock = mocker.MagicMock()
    session_mock.client.return_value = client = mocker.MagicMock()
    aws_api.session = session_mock
    sub_api = aws_api._init_sub_api(api_cls)

    assert isinstance(sub_api, api_cls)
    session_mock.client.assert_called_once_with(client_name)
    assert aws_api._session_clients == [client]


def test_aws_api_typed_api_sts(aws_api: AWSApi) -> None:
    sub_api = aws_api.sts
    assert isinstance(sub_api, AWSApiSts)


def test_aws_api_typed_api_organizations(aws_api: AWSApi) -> None:
    sub_api = aws_api.organizations
    assert isinstance(sub_api, AWSApiOrganizations)


def test_aws_api_typed_api_iam(aws_api: AWSApi) -> None:
    sub_api = aws_api.iam
    assert isinstance(sub_api, AWSApiIam)


def test_aws_api_typed_api_assume_role(aws_api: AWSApi, mocker: MockerFixture) -> None:
    mocker.patch.object(AWSApi, "sts")
    aws_api.sts.assume_role.return_value = AWSCredentials(  # type: ignore
        AccessKeyId="access_key",
        SecretAccessKey="secret_key",
        SessionToken="session_token",
        Expiration="1",
    )
    new_aws_api = aws_api.assume_role("account_id", "role")
    assert isinstance(new_aws_api, AWSApi)
    aws_api.sts.assume_role.assert_called_once_with(  # type: ignore
        account_id="account_id", role="role"
    )


def test_aws_api_typed_api_get_temporary_credentials(
    aws_api: AWSApi, mocker: MockerFixture
) -> None:
    mocker.patch.object(AWSApi, "sts")
    aws_api.sts.get_session_token.return_value = AWSCredentials(  # type: ignore
        AccessKeyId="access_key",
        SecretAccessKey="secret_key",
        SessionToken="session_token",
        Expiration="1",
    )
    new_aws_api = aws_api.temporary_session(duration_seconds=1)
    assert isinstance(new_aws_api, AWSApi)
    aws_api.sts.get_session_token.assert_called_once_with(  # type: ignore
        duration_seconds=1
    )
