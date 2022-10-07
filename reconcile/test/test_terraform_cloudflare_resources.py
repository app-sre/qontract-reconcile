import pytest
from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_resources import (
    CloudflareAccountV1,
    CloudflareZoneRecordV1,
    CloudflareZoneWorkerV1,
    NamespaceTerraformProviderResourceCloudflareV1,
    NamespaceTerraformResourceCloudflareZoneV1,
    NamespaceV1,
    TerraformCloudflareResourcesQueryData,
    CloudflareZoneCertificateV1,
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
