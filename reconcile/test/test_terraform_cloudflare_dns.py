import pytest

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.terraform_cloudflare_dns.terraform_cloudflare_zones import (
    AWSAccountV1,
    CloudflareAccountV1,
    CloudflareDnsRecordV1,
    CloudflareDnsZoneV1,
)
from reconcile.terraform_cloudflare_dns import (
    DEFAULT_EXCLUDE_KEY,
    DEFAULT_NAMESPACE,
    DEFAULT_PROVIDER,
    DEFAULT_PROVISIONER_PROVIDER,
    cloudflare_dns_zone_to_external_resource,
    ensure_record_number_not_exceed_max,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec


@pytest.fixture
def cloudflare_records():
    return [
        CloudflareDnsRecordV1(
            identifier="id0",
            name="subdomain",
            type="CNAME",
            ttl=10,
            value="foo.com",
            priority=None,
            data=None,
            proxied=None,
        ),
        CloudflareDnsRecordV1(
            identifier="id1",
            name="subdomain1",
            type="CNAME",
            ttl=10,
            value="foo1.com",
            priority=None,
            data=None,
            proxied=None,
        ),
    ]


@pytest.fixture
def cloudflare_dns_zones(cloudflare_account, cloudflare_records):
    return [
        CloudflareDnsZoneV1(
            identifier="zoneid",
            zone="fakezone.com",
            account=cloudflare_account,
            records=cloudflare_records,
            type="full",
            plan="free",
            delete=False,
            max_records=1,
        )
    ]


@pytest.fixture
def cloudflare_account(aws_account):
    return CloudflareAccountV1(
        name="fakeaccount",
        type="free",
        description="description",
        providerVersion="0.0",
        enforceTwofactor=False,
        apiCredentials=VaultSecret(
            path="foo/bar", field="foo", format="bar", version=2
        ),
        terraformStateAccount=aws_account,
        deletionApprovals=None,
    )


@pytest.fixture
def aws_account():
    return AWSAccountV1(
        name="foo",
        consoleUrl="url",
        terraformUsername="bar",
        automationToken=VaultSecret(path="foo", field="bar", format=None, version=None),
        terraformState=None,
    )


def test_cloudflare_dns_zone_to_external_resource(cloudflare_dns_zones):
    expected_external_resource = ExternalResourceSpec(
        provision_provider=DEFAULT_PROVISIONER_PROVIDER,
        provisioner={"name": "fakeaccount-zoneid"},
        namespace=DEFAULT_NAMESPACE,
        resource=cloudflare_dns_zones[0].dict(
            by_alias=True, exclude=DEFAULT_EXCLUDE_KEY
        ),
    )
    expected_external_resource.resource["provider"] = DEFAULT_PROVIDER
    expected_external_resource.resource["records"] = [
        record.dict(by_alias=True) for record in cloudflare_dns_zones[0].records
    ]
    expected_result = [expected_external_resource]

    result = cloudflare_dns_zone_to_external_resource(cloudflare_dns_zones)

    assert result == expected_result


def test_evaluate_record_number_too_many_raise_exception(cloudflare_dns_zones):
    with pytest.raises(RuntimeError):
        ensure_record_number_not_exceed_max(cloudflare_dns_zones, default_max_records=1)


def test_evaluate_record_number_happy_path(cloudflare_dns_zones):
    cloudflare_dns_zones[0].max_records = 2
    ensure_record_number_not_exceed_max(cloudflare_dns_zones, default_max_records=1)
