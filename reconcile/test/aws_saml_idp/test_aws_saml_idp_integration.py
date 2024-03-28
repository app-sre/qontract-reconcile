from collections.abc import Callable

import httpretty as _httpretty

from reconcile.aws_saml_idp.integration import AwsSamlIdpIntegration, SamlIdpConfig
from reconcile.gql_definitions.aws_saml_idp.aws_accounts import AWSAccountV1


def test_aws_saml_idp_get_early_exit_desired_state(
    intg: AwsSamlIdpIntegration, fixture_query_func: Callable
) -> None:
    state = intg.get_early_exit_desired_state(query_func=fixture_query_func)
    assert "accounts" in state


def test_aws_saml_idp_get_aws_accounts(
    gql_class_factory: Callable,
    intg: AwsSamlIdpIntegration,
    fixture_query_func: Callable,
) -> None:
    assert intg.get_aws_accounts(fixture_query_func) == [
        gql_class_factory(
            AWSAccountV1,
            {
                "sso": True,
                "name": "account-1",
                "uid": "1",
                "resourcesDefaultRegion": "us-east-1",
                "supportedDeploymentRegions": ["us-east-1", "us-east-2"],
                "providerVersion": "3.76.0",
                "accountOwners": [{"name": "owner", "email": "email@example.com"}],
                "automationToken": {"path": "/path/to/token", "field": "all"},
                "enableDeletion": True,
                "premiumSupport": True,
            },
        ),
        gql_class_factory(
            AWSAccountV1,
            {
                "sso": False,
                "name": "account-2",
                "uid": "1",
                "resourcesDefaultRegion": "us-east-1",
                "supportedDeploymentRegions": ["us-east-1", "us-east-2"],
                "providerVersion": "3.76.0",
                "accountOwners": [{"name": "owner", "email": "email@example.com"}],
                "automationToken": {"path": "/path/to/token", "field": "all"},
                "enableDeletion": True,
                "premiumSupport": True,
            },
        ),
    ]
    assert intg.get_aws_accounts(fixture_query_func, account_name="account-1") == [
        gql_class_factory(
            AWSAccountV1,
            {
                "sso": True,
                "name": "account-1",
                "uid": "1",
                "resourcesDefaultRegion": "us-east-1",
                "supportedDeploymentRegions": ["us-east-1", "us-east-2"],
                "providerVersion": "3.76.0",
                "accountOwners": [{"name": "owner", "email": "email@example.com"}],
                "automationToken": {"path": "/path/to/token", "field": "all"},
                "enableDeletion": True,
                "premiumSupport": True,
            },
        )
    ]


def test_aws_saml_idp_build_saml_idp_config(
    intg: AwsSamlIdpIntegration, aws_accounts: list[AWSAccountV1]
) -> None:
    assert intg.build_saml_idp_config(aws_accounts, "saml-idp", "metadata") == [
        SamlIdpConfig(account_name="account-1", name="saml-idp", metadata="metadata")
    ]


def test_aws_saml_idp_get_saml_metadata(
    intg: AwsSamlIdpIntegration, httpretty: _httpretty
) -> None:
    url = "https://saml-metadata-url.example.com/metadata.xml"
    httpretty.register_uri("GET", url, body="metadata")
    assert intg.get_saml_metadata(saml_metadata_url=url) == "metadata"
