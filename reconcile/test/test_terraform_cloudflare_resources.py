import logging

import pytest

import reconcile.terraform_cloudflare_resources as integ
from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    AWSAccountV1,
    AWSTerraformStateIntegrationsV1,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    CloudflareAccountV1 as CFAccountV1,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    DeletionApprovalV1,
    TerraformCloudflareAccountsQueryData,
    TerraformStateAWSV1,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    CloudflareAccountV1,
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
                provider="cloudflare_zone",
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
            ),
        ],
    )


@pytest.fixture
def mock_gql(mocker):
    mocker.patch("reconcile.terraform_cloudflare_resources.gql", autospec=True)


@pytest.fixture
def mock_vault_secret(mocker):
    mocked_vault_secret = mocker.patch(
        "reconcile.terraform_cloudflare_resources.get_app_interface_vault_settings",
        autospec=True,
    )
    mocked_vault_secret.return_value = AppInterfaceSettingsV1(vault=False)


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
                    providerVersion="0.33.x",
                    apiCredentials=VaultSecret(
                        path="somepath",
                        field="key",
                        version=1,
                        format="??",
                    ),
                    terraformStateAccount=AWSAccountV1(
                        name="awsaccoutn",
                        automationToken=VaultSecret(
                            path="someotherpath",
                            field="token",
                            version=1,
                            format="",
                        ),
                        terraformState=TerraformStateAWSV1(
                            provider="",
                            bucket="",
                            region="",
                            integrations=[
                                AWSTerraformStateIntegrationsV1(
                                    integration="terraform-cloudflare-resources", key=""
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
def mock_cloudflare_resources(mocker, external_resources):
    mocked_cloudflare_resources = mocker.patch(
        "reconcile.terraform_cloudflare_resources.terraform_cloudflare_resources",
        autospec=True,
    )
    mocked_cloudflare_resources.query.return_value = external_resources


def test_cloudflare_accounts_validation(
    mocker, caplog, mock_gql, mock_vault_secret, mock_cloudflare_resources
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
    assert ["No Cloudflare accounts were detected, nothing to do."] == [
        rec.message for rec in caplog.records
    ]


def test_namespace_validation(
    mocker, caplog, mock_gql, mock_vault_secret, mock_cloudflare_accounts
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
    assert ["No namespaces were detected, nothing to do."] == [
        rec.message for rec in caplog.records
    ]


def test_cloudflare_namespace_validation(
    mocker, caplog, mock_gql, mock_vault_secret, mock_cloudflare_accounts
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
    assert ["No cloudflare namespaces were detected, nothing to do."] == [
        rec.message for rec in caplog.records
    ]
