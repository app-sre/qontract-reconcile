from collections.abc import Callable, Mapping
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)
from reconcile.gql_definitions.terraform_init.aws_accounts import AWSAccountV1
from reconcile.terraform_init.integration import (
    TerraformInitIntegration,
    TerraformInitIntegrationParams,
)
from reconcile.terraform_init.merge_request_manager import MergeRequestManager
from reconcile.test.fixtures import Fixtures
from qontract_utils.aws_api_typed.api import AWSApi


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("terraform_init")


@pytest.fixture
def raw_fixture_data(fx: Fixtures) -> dict[str, Any]:
    return fx.get_anymarkup("accounts.yml")


@pytest.fixture
def intg(mocker: MockerFixture) -> TerraformInitIntegration:
    integ = TerraformInitIntegration(TerraformInitIntegrationParams())
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
def external_resource_settings(
    fx: Fixtures,
    data_factory: Callable[
        [type[ExternalResourcesSettingsV1], Mapping[str, Any]], Mapping[str, Any]
    ],
) -> dict[str, Any]:
    return {
        "settings": [
            data_factory(
                ExternalResourcesSettingsV1,
                fx.get_anymarkup("settings.yml"),
            )
        ]
    }


@pytest.fixture
def aws_accounts(
    query_func: Callable, intg: TerraformInitIntegration
) -> list[AWSAccountV1]:
    return intg.get_aws_accounts(query_func)


@pytest.fixture
def aws_api(mocker: MockerFixture) -> MagicMock:
    mocker.patch("reconcile.aws_account_manager.integration.AWSApi")
    return mocker.MagicMock(spec=AWSApi)


@pytest.fixture
def merge_request_manager(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock(spec=MergeRequestManager)
