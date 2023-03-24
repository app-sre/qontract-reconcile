import pytest

from reconcile.gql_definitions.terraform_cloudflare_dns.terraform_cloudflare_zones import (
    CloudflareDnsRecordV1,
)
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    CloudflareAccountV1,
    CloudflareZoneCertificateV1,
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
                argo={
                    "tiered_caching": True,
                    "smart_routing": True,
                },
                tiered_cache={
                    "cache_type": "smart",
                },
                cache_reserve={
                    "enabled": True,
                },
                records=[
                    CloudflareDnsRecordV1(
                        name="record",
                        type="CNAME",
                        ttl=5,
                        value="example.com",
                        proxied=False,
                        identifier="record",
                        priority=None,
                        data=None,
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
