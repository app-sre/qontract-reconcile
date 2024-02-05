from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

import pytest

from reconcile.aws_saml_idp.integration import (
    AwsSamlIdpIntegration,
    AwsSamlIdpIntegrationParams,
)
from reconcile.gql_definitions.aws_saml_idp.aws_accounts import AWSAccountV1
from reconcile.test.fixtures import Fixtures


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("aws_saml_idp")


@pytest.fixture
def intg() -> AwsSamlIdpIntegration:
    return AwsSamlIdpIntegration(
        AwsSamlIdpIntegrationParams(
            saml_idp_name="saml-idp",
            saml_metadata_url="https://saml-metadata-url.example.com/metadata.xml",
        )
    )


@pytest.fixture
def fixture_query_func(
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


@pytest.fixture
def aws_accounts(
    intg: AwsSamlIdpIntegration, fixture_query_func: Callable
) -> list[AWSAccountV1]:
    return intg.get_aws_accounts(fixture_query_func)
