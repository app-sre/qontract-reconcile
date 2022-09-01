import pytest
from reconcile.gql_definitions.terraform_resources_cloudflare.terraform_resources_cloudflare import (
    AWSAccountV1,
    CloudflareAccountV1,
    NamespaceTerraformProviderResourceCloudflareV1,
    NamespaceTerraformResourceCloudflareZoneV1,
    NamespaceV1,
    TerraformResourcesCloudflareQueryData,
    TerraformStateAWSV1,
    VaultSecretV1,
)
from reconcile.terraform_resources_cloudflare import build_specs
from reconcile.utils.external_resource_spec import ExternalResourceSpec


@pytest.fixture
def query_data(external_resources):
    return TerraformResourcesCloudflareQueryData(
        namespaces=[
            NamespaceV1(name="namespace1", externalResources=[external_resources])
        ],
    )


@pytest.fixture
def provisioner_config():
    return CloudflareAccountV1(
        name="cfaccount1",
        providerVersion="3.18.0",
        apiCredentials=VaultSecretV1(
            path="",
            field="",
        ),
        terraformStateAccount=AWSAccountV1(
            name="awsaccount1",
            automationToken=VaultSecretV1(
                path="",
                field="",
            ),
            terraformState=TerraformStateAWSV1(
                provider="s3",
                bucket="bucket1",
                region="region1",
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
                provider="zone",
                zone="testzone1.com",
                plan="enterprise",
                type="full",
                settings=None,
                argo=None,
                records=[],
                workers=[],
            ),
            NamespaceTerraformResourceCloudflareZoneV1(
                provider="zone",
                zone="testzone2.com",
                plan="enterprise",
                type="full",
                settings=None,
                argo=None,
                records=[],
                workers=[],
            ),
            NamespaceTerraformResourceCloudflareZoneV1(
                provider="zone",
                zone="testzone3.com",
                plan="enterprise",
                type="full",
                settings=None,
                argo=None,
                records=[],
                workers=[],
            ),
        ],
    )


def test_build_specs_(settings, gh_instance, query_data):
    actual = build_specs(settings, gh_instance, query_data)
    expected = [
        ExternalResourceSpec(
            "cloudflare_zone",
            {"name": "cfaccount1", "automationToken": {}},
            {
                "provider": "cloudflare_zone",
                "identifier": "testzone1_com",
                "zone": "testzone1.com",
                "plan": "enterprise",
                "type": "full",
                "settings": None,
                "argo": None,
                "records": [],
                "workers": [],
            },
            {},
        ),
        ExternalResourceSpec(
            "cloudflare_zone",
            {"name": "cfaccount1", "automationToken": {}},
            {
                "provider": "cloudflare_zone",
                "identifier": "testzone2_com",
                "zone": "testzone2.com",
                "plan": "enterprise",
                "type": "full",
                "settings": None,
                "argo": None,
                "records": [],
                "workers": [],
            },
            {},
        ),
        ExternalResourceSpec(
            "cloudflare_zone",
            {"name": "cfaccount1", "automationToken": {}},
            {
                "provider": "cloudflare_zone",
                "identifier": "testzone3_com",
                "zone": "testzone3.com",
                "plan": "enterprise",
                "type": "full",
                "settings": None,
                "argo": None,
                "records": [],
                "workers": [],
            },
            {},
        ),
    ]

    assert actual == expected
