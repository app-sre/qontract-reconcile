from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.aws_account_manager.integration import (
    AwsAccountMgmtIntegration,
    AwsAccountMgmtIntegrationParams,
)
from reconcile.aws_account_manager.merge_request_manager import MergeRequestManager
from reconcile.aws_account_manager.reconciler import AWSReconciler
from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    AWSAccountRequestV1,
    AWSAccountV1,
)
from reconcile.gql_definitions.fragments.aws_account_managed import AWSAccountManaged
from reconcile.test.fixtures import Fixtures
from qontract_utils.aws_api_typed.api import AWSApi
from reconcile.utils.state import State


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("aws_account_manager")


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("accounts.yml")


@pytest.fixture
def intg(mocker: MockerFixture) -> AwsAccountMgmtIntegration:
    integ = AwsAccountMgmtIntegration(
        AwsAccountMgmtIntegrationParams(flavor="commercial")
    )
    integ._secret_reader = mocker.MagicMock()
    integ._secret_reader.read_all_secret.return_value = {  # type: ignore
        "aws_access_key_id": "access_key",
        "aws_secret_access_key": "secret_key",
    }
    return integ


@pytest.fixture
def query_func(
    data_factory: Callable[[type[AWSAccountV1], Mapping[str, Any]], Mapping[str, Any]],
    raw_fixture_data: dict[str, Any],
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "accounts": [
                data_factory(AWSAccountV1, item)
                for item in raw_fixture_data["accounts"]
            ]
        }

    return q


@pytest.fixture
def aws_accounts(
    query_func: Callable, intg: AwsAccountMgmtIntegration
) -> tuple[list[AWSAccountV1], list[AWSAccountV1]]:
    return intg.get_aws_accounts(query_func)


@pytest.fixture
def payer_accounts(
    aws_accounts: tuple[list[AWSAccountV1], list[AWSAccountV1]],
) -> list[AWSAccountV1]:
    return aws_accounts[0]


@pytest.fixture
def payer_account(payer_accounts: list[AWSAccountV1]) -> AWSAccountV1:
    return payer_accounts[0]


@pytest.fixture
def account_request(payer_account: AWSAccountV1) -> AWSAccountRequestV1:
    if not payer_account.account_requests:
        raise NotImplementedError(
            f"{payer_account.name} has no account requests. Don't mess with the test fixtures! :)"
        )
    return payer_account.account_requests[0]


@pytest.fixture
def non_org_accounts(
    aws_accounts: tuple[list[AWSAccountV1], list[AWSAccountV1]],
) -> list[AWSAccountV1]:
    return aws_accounts[1]


@pytest.fixture
def non_org_account(non_org_accounts: list[AWSAccountV1]) -> AWSAccountV1:
    return non_org_accounts[0]


@pytest.fixture
def org_account(payer_account: AWSAccountV1) -> AWSAccountManaged:
    if not payer_account.organization_accounts:
        raise NotImplementedError(
            f"{payer_account.name} has no organization accounts. Don't mess with the test fixtures! :)"
        )
    return payer_account.organization_accounts[0]


@pytest.fixture
def aws_api(mocker: MockerFixture) -> MagicMock:
    mocker.patch("reconcile.aws_account_manager.integration.AWSApi")
    return mocker.MagicMock(spec=AWSApi)


@pytest.fixture
def reconciler(mocker: MockerFixture) -> MagicMock:
    m = mocker.MagicMock(spec=AWSReconciler)
    m.state = mocker.MagicMock(spec=State)
    return m


@pytest.fixture
def merge_request_manager(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock(spec=MergeRequestManager)
