import pytest
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    AWSAccountV1,
    CloudflareAccountV1,
    CloudflareZoneRecordV1,
    CloudflareZoneWorkerV1,
    NamespaceTerraformProviderResourceCloudflareV1,
    NamespaceTerraformResourceCloudflareZoneV1,
    NamespaceV1,
    TerraformCloudflareResourcesQueryData,
    TerraformStateAWSV1,
    VaultSecretV1,
)


@pytest.fixture
def query_data(external_resources):
    return TerraformCloudflareResourcesQueryData(
        namespaces=[
            NamespaceV1(
                name="namespace1",
                managedExternalResources=True,
                externalResources=[external_resources],
            )
        ],
    )


@pytest.fixture
def provisioner_config():
    return CloudflareAccountV1(
        name="cfaccount",
        providerVersion="3.22.0",
        apiCredentials=VaultSecretV1(
            path="",
            field="",
        ),
        terraformStateAccount=AWSAccountV1(
            name="awsaccount",
            automationToken=VaultSecretV1(
                path="",
                field="",
            ),
            terraformState=TerraformStateAWSV1(
                provider="s3",
                bucket="bucket",
                region="region",
                integrations=[],
            ),
        ),
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
                argo={
                    "tiered_caching": True,
                    "smart_routing": True,
                },
                records=[
                    CloudflareZoneRecordV1(
                        name="record",
                        type="CNAME",
                        ttl=5,
                        value="example.com",
                        proxied=False,
                    ),
                ],
                workers=[
                    CloudflareZoneWorkerV1(
                        identifier="testworker",
                        pattern="testzone.com/.*",
                        script_name="testscript",
                    )
                ],
            ),
        ],
    )
