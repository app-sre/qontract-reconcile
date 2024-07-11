import logging
from unittest.mock import call

import pytest

import reconcile.terraform_cloudflare_resources as integ
from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    AWSAccountV1,
    AWSTerraformStateIntegrationsV1,
    DeletionApprovalV1,
    TerraformCloudflareAccountsQueryData,
    TerraformStateAWSV1,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    CloudflareAccountV1 as CFAccountV1,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    CertificateSecretV1,
    CloudflareAccountV1,
    CloudflareCustomSSLCertificateV1,
    CloudflareDnsRecordV1,
    CloudflareZoneArgoV1,
    CloudflareZoneCacheReserveV1,
    CloudflareZoneCertificateV1,
    CloudflareZoneTieredCacheV1,
    CloudflareZoneWorkerV1,
    ClusterV1,
    NamespaceTerraformProviderResourceCloudflareV1,
    NamespaceTerraformResourceCloudflareZoneV1,
    NamespaceV1,
    TerraformCloudflareResourcesQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils.secret_reader import (
    SecretReaderBase,
)


@pytest.fixture
def query_data(external_resources):
    return TerraformCloudflareResourcesQueryData(
        namespaces=[
            NamespaceV1(
                name="namespace1",
                clusterAdmin=True,
                cluster=ClusterV1(
                    name="test-cluster",
                    serverUrl="http://localhost",
                    insecureSkipTLSVerify=None,
                    jumpHost=None,
                    automationToken=None,
                    clusterAdminAutomationToken=None,
                    spec=None,
                    internal=None,
                    disable=None,
                ),
                managedExternalResources=True,
                externalResources=[external_resources],
            )
        ],
    )


@pytest.fixture
def provisioner_config():
    return CloudflareAccountV1(
        name="cfaccount",
    )


@pytest.fixture
def external_resources(provisioner_config):
    return NamespaceTerraformProviderResourceCloudflareV1(
        provider="cloudflare",
        provisioner=provisioner_config,
        resources=[
            NamespaceTerraformResourceCloudflareZoneV1(
                provider="zone",
                identifier="testzone-com",
                zone="testzone.com",
                plan="enterprise",
                type="full",
                settings='{"foo": "bar"}',
                argo=CloudflareZoneArgoV1(
                    tiered_caching=True,
                    smart_routing=True,
                ),
                tiered_cache=CloudflareZoneTieredCacheV1(
                    cache_type="smart",
                ),
                cache_reserve=CloudflareZoneCacheReserveV1(enabled=True),
                records=[
                    CloudflareDnsRecordV1(
                        name="record",
                        type="CNAME",
                        ttl=5,
                        value="example.com",
                        proxied=False,
                        identifier="record",
                    ),
                ],
                workers=[
                    CloudflareZoneWorkerV1(
                        identifier="testworker",
                        pattern="testzone.com/.*",
                        script_name="testscript",
                    )
                ],
                certificates=[
                    CloudflareZoneCertificateV1(
                        identifier="testcert",
                        type="advanced",
                        hosts=["testzone.com"],
                        validation_method="txt",
                        validity_days=90,
                        certificate_authority="lets_encrypt",
                        cloudflare_branding=False,
                        wait_for_active_status=False,
                    )
                ],
                custom_ssl_certificates=[
                    CloudflareCustomSSLCertificateV1(
                        identifier="testcustomssl",
                        type="legacy_custom",
                        bundle_method="ubiquitous",
                        geo_restrictions="us",
                        certificate_secret=CertificateSecretV1(
                            certificate=VaultSecret(
                                path="certificate/secret/cert/path",
                                field="certificate.crt",
                                format="plain",
                                version=1,
                            ),
                            key=VaultSecret(
                                path="certificate/secret/key/path",
                                field="certificate.key",
                                format="plain",
                                version=1,
                            ),
                        ),
                    )
                ],
            ),
        ],
    )


@pytest.fixture
def mock_gql(mocker):
    mocker.patch("reconcile.terraform_cloudflare_resources.gql", autospec=True)


@pytest.fixture
def mock_app_interface_vault_settings(mocker):
    mocked_app_interface_vault_settings = mocker.patch(
        "reconcile.terraform_cloudflare_resources.get_app_interface_vault_settings",
        autospec=True,
    )
    mocked_app_interface_vault_settings.return_value = AppInterfaceSettingsV1(
        vault=True
    )


def secret_reader_side_effect(*args):
    if args[0] == {
        "path": "aws-account-path",
        "field": "token",
        "version": 1,
        "q_format": "plain",
    }:
        aws_acct_creds = {}
        aws_acct_creds["aws_access_key_id"] = "key_id"
        aws_acct_creds["aws_secret_access_key"] = "access_key"
        return aws_acct_creds

    if args[0] == {
        "path": "cf-account-path",
        "field": "key",
        "version": 1,
        "q_format": "plain",
    }:
        cf_acct_creds = {}
        cf_acct_creds["api_token"] = "api_token"
        cf_acct_creds["account_id"] = "account_id"
        return cf_acct_creds


@pytest.fixture
def mock_create_secret_reader(mocker):
    secret_reader = mocker.Mock(SecretReaderBase)
    secret_reader.read_all_secret.side_effect = secret_reader_side_effect

    mocked_create_secret_reader = mocker.patch(
        "reconcile.terraform_cloudflare_resources.create_secret_reader",
        autospec=True,
    )

    mocked_create_secret_reader.return_value = secret_reader


@pytest.fixture
def mock_cloudflare_accounts(mocker):
    mocked_cloudflare_accounts = mocker.patch(
        "reconcile.terraform_cloudflare_resources.terraform_cloudflare_accounts",
        autospec=True,
    )
    mocked_cloudflare_accounts.query.return_value = (
        TerraformCloudflareAccountsQueryData(
            accounts=[
                CFAccountV1(
                    name="cfaccount",
                    description="cfaccount",
                    providerVersion="0.33.x",
                    apiCredentials=VaultSecret(
                        path="cf-account-path",
                        field="key",
                        version=1,
                        format="plain",
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="awsaccoutn",
                        automationToken=VaultSecret(
                            path="aws-account-path",
                            field="token",
                            version=1,
                            format="plain",
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="s3",
                            bucket="app-interface",
                            region="us-east-1",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-resources",
                                    key="somekey.tfstate",
                                )
                            ],
                        ),
                    ),
                    deletionApprovals=[
                        DeletionApprovalV1(expiration="", name="", type="")
                    ],
                    enforceTwofactor=False,
                    type="?????",
                )
            ]
        )
    )


@pytest.fixture
def mock_cloudflare_resources(mocker, query_data):
    mocked_cloudflare_resources = mocker.patch(
        "reconcile.terraform_cloudflare_resources.terraform_cloudflare_resources",
        autospec=True,
    )
    mocked_cloudflare_resources.query.return_value = query_data


@pytest.fixture
def mock_terraform_client(mocker):
    mocked_tf_client = mocker.patch(
        "reconcile.terraform_cloudflare_resources.TerraformClient", autospec=True
    )
    mocked_tf_client.return_value.plan.return_value = False, None
    return mocked_tf_client


def test_cloudflare_accounts_validation(
    mocker,
    caplog,
    mock_gql,
    mock_app_interface_vault_settings,
    mock_cloudflare_resources,
):
    # Mocking accounts with an empty response
    mocked_cloudflare_accounts = mocker.patch(
        "reconcile.terraform_cloudflare_resources.terraform_cloudflare_accounts",
        autospec=True,
    )
    mocked_cloudflare_accounts.query.return_value = (
        TerraformCloudflareAccountsQueryData(accounts=[])
    )

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        integ.run(True, None, False, 10)
    assert sample.value.code == 0
    assert [rec.message for rec in caplog.records] == [
        "No Cloudflare accounts were detected, nothing to do."
    ]


def test_namespace_validation(
    mocker,
    caplog,
    mock_gql,
    mock_app_interface_vault_settings,
    mock_cloudflare_accounts,
):
    # Mocking resources without namespaces
    mocked_resources = mocker.patch(
        "reconcile.terraform_cloudflare_resources.terraform_cloudflare_resources",
        autospec=True,
    )
    mocked_resources.query.return_value = TerraformCloudflareResourcesQueryData(
        namespaces=[],
    )

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        integ.run(True, None, False, 10)
    assert sample.value.code == 0
    assert [rec.message for rec in caplog.records] == [
        "No namespaces were detected, nothing to do."
    ]


def test_cloudflare_namespace_validation(
    mocker,
    caplog,
    mock_gql,
    mock_app_interface_vault_settings,
    mock_cloudflare_accounts,
):
    # Mocking resources without cloudflare namespaces
    mocked_resources = mocker.patch(
        "reconcile.terraform_cloudflare_resources.terraform_cloudflare_resources",
        autospec=True,
    )

    mocked_resources.query.return_value = TerraformCloudflareResourcesQueryData(
        namespaces=[
            NamespaceV1(
                name="namespace1",
                clusterAdmin=True,
                cluster=ClusterV1(
                    name="test-cluster",
                    serverUrl="http://localhost",
                    insecureSkipTLSVerify=None,
                    jumpHost=None,
                    automationToken=None,
                    clusterAdminAutomationToken=None,
                    spec=None,
                    internal=None,
                    disable=None,
                ),
                managedExternalResources=True,
                externalResources=[],
            )
        ],
    )

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        integ.run(True, None, False, 10)
    assert sample.value.code == 0
    assert [rec.message for rec in caplog.records] == [
        "No cloudflare namespaces were detected, nothing to do."
    ]


def custom_ssl_secret_reader_side_effect(*args):
    """For use of secret_reader inside cloudflare client"""
    if args[0] == {
        "path": "certificate/secret/cert/path",
        "field": "certificate.crt",
        "version": 1,
        "q_format": "plain",
    }:
        return "----- CERTIFICATE -----"

    if args[0] == {
        "path": "certificate/secret/cert/path",
        "field": "certificate.key",
        "version": 1,
        "q_format": "plain",
    }:
        return "----- KEY -----"


def test_terraform_cloudflare_resources_dry_run(
    mocker,
    mock_gql,
    mock_create_secret_reader,
    mock_terraform_client,
    mock_app_interface_vault_settings,
    mock_cloudflare_accounts,
    mock_cloudflare_resources,
):
    # Mocking vault settings and secret reader inside cloudflare_client
    mocker.patch(
        "reconcile.utils.terrascript.cloudflare_resources.get_app_interface_vault_settings",
        atospec=True,
    )
    secret_reader = mocker.Mock(SecretReaderBase)
    secret_reader.read.side_effect = custom_ssl_secret_reader_side_effect
    create_secret_reader = mocker.patch(
        "reconcile.utils.terrascript.cloudflare_resources.create_secret_reader",
        autospec=True,
    )
    create_secret_reader.return_value = secret_reader
    with pytest.raises(SystemExit) as sample:
        integ.run(True, None, False, 10)
    assert sample.value.code == ExitCodes.SUCCESS
    assert mock_terraform_client.called is True
    assert call().apply() not in mock_terraform_client.method_calls
