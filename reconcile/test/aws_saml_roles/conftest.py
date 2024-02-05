from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

import pytest

from reconcile.aws_saml_roles.integration import (
    AwsSamlRolesIntegration,
    AwsSamlRolesIntegrationParams,
)
from reconcile.gql_definitions.aws_saml_roles.aws_accounts import AWSAccountV1
from reconcile.gql_definitions.aws_saml_roles.aws_groups import AWSGroupV1
from reconcile.test.fixtures import Fixtures


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("aws_saml_roles")


@pytest.fixture
def intg() -> AwsSamlRolesIntegration:
    return AwsSamlRolesIntegration(
        AwsSamlRolesIntegrationParams(
            saml_idp_name="saml-idp",
            max_session_duration_hours=1,
        )
    )


@pytest.fixture
def fixture_query_func(
    fx: Fixtures,
    data_factory: Callable[[type[AWSGroupV1], Mapping[str, Any]], Mapping[str, Any]],
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "aws_groups": [
                data_factory(AWSGroupV1, item)
                for item in fx.get_anymarkup("aws_groups.yml")["aws_groups"]
            ]
        }

    return q


@pytest.fixture
def fixture_query_func_aws_accounts(
    fx: Fixtures,
    data_factory: Callable[[type[AWSAccountV1], Mapping[str, Any]], Mapping[str, Any]],
) -> Callable:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "accounts": [
                data_factory(AWSAccountV1, item)
                for item in fx.get_anymarkup("aws_accounts.yml")["accounts"]
            ]
        }

    return q
