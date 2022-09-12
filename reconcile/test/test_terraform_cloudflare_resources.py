import pytest
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    AWSAccountV1,
    CloudflareAccountV1,
    CloudflareZoneRecordV1,
    CloudflareZoneWorkerScriptContentFromGithubV1,
    CloudflareZoneWorkerScriptV1,
    CloudflareZoneWorkerScriptVarsV1,
    CloudflareZoneWorkerV1,
    NamespaceTerraformProviderResourceCloudflareV1,
    NamespaceTerraformResourceCloudflareZoneV1,
    NamespaceV1,
    TerraformCloudflareResourcesQueryData,
    TerraformStateAWSV1,
    VaultSecretV1,
)
from reconcile.terraform_cloudflare_resources import build_specs
from reconcile.utils.external_resource_spec import ExternalResourceSpec

import reconcile.terraform_cloudflare_resources as integ


@pytest.fixture
def query_data(external_resources):
    return TerraformCloudflareResourcesQueryData(
        namespaces=[
            NamespaceV1(name="namespace1", externalResources=[external_resources])
        ],
    )


@pytest.fixture
def settings():
    return {}


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
                provider="zone",
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
                        script=CloudflareZoneWorkerScriptV1(
                            name="testscript",
                            content_from_github=CloudflareZoneWorkerScriptContentFromGithubV1(
                                repo="foo",
                                path="bar",
                                ref="baz",
                            ),
                            vars=[
                                CloudflareZoneWorkerScriptVarsV1(
                                    name="somename",
                                    text="sometext",
                                )
                            ],
                        ),
                    )
                ],
            ),
        ],
    )


def test_build_specs(mocker, query_data):
    get_github_file = mocker.patch.object(integ, "get_github_file")
    get_github_file.return_value = "foo"

    actual = build_specs(query_data)
    expected = [
        ExternalResourceSpec(
            "cloudflare_zone",
            {"name": "cfaccount", "automationToken": {}},
            {
                "provider": "cloudflare_zone",
                "identifier": "testzone_com",
                "zone": "testzone.com",
                "plan": "enterprise",
                "type": "full",
                "settings": {
                    "foo": "bar",
                },
            },
            {},
        ),
        ExternalResourceSpec(
            "cloudflare_argo",
            {"name": "cfaccount", "automationToken": {}},
            {
                "provider": "cloudflare_argo",
                "identifier": "testzone_com",
                "depends_on": ["cloudflare_zone.testzone_com"],
                "zone_id": "${cloudflare_zone.testzone_com.id}",
                "smart_routing": "on",
                "tiered_caching": "on",
            },
            {},
        ),
        ExternalResourceSpec(
            "cloudflare_record",
            {"name": "cfaccount", "automationToken": {}},
            {
                "provider": "cloudflare_record",
                "identifier": "record",
                "depends_on": ["cloudflare_zone.testzone_com"],
                "zone_id": "${cloudflare_zone.testzone_com.id}",
                "name": "record",
                "type": "CNAME",
                "ttl": 5,
                "value": "example.com",
                "proxied": False,
            },
            {},
        ),
        ExternalResourceSpec(
            "cloudflare_worker",
            {"name": "cfaccount", "automationToken": {}},
            {
                "provider": "cloudflare_worker",
                "identifier": "testworker",
                "depends_on": ["cloudflare_zone.testzone_com"],
                "zone_id": "${cloudflare_zone.testzone_com.id}",
                "pattern": "testzone.com/.*",
                "script_name": "testscript",
                "script_content": "foo",
                "script_vars": [{"name": "somename", "text": "sometext"}],
            },
            {},
        ),
    ]

    assert actual == expected
