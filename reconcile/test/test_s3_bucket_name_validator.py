import pytest

from reconcile.gql_definitions.s3_bucket_name_validator.s3_bucket_name_validator import (
    ExternalResourcesProvisionerV1,
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceAWSV1,
    NamespaceTerraformResourceS3CloudFrontV1,
    NamespaceTerraformResourceS3V1,
    NamespaceV1,
    S3BucketNameValidatorQueryData,
)
from reconcile.s3_bucket_name_validator import validate_no_duplicate_bucket_names


def build_namespace(
    name: str,
    account: str,
    s3_identifiers: list[str] | None = None,
    cloudfront_identifiers: list[str] | None = None,
    delete: bool = False,
    managed_external_resources: bool = True,
) -> NamespaceV1:
    resources: list[NamespaceTerraformResourceAWSV1] = [
        NamespaceTerraformResourceS3V1(provider="s3", identifier=identifier)
        for identifier in s3_identifiers or []
    ]
    resources += [
        NamespaceTerraformResourceS3CloudFrontV1(
            provider="s3-cloudfront", identifier=identifier
        )
        for identifier in cloudfront_identifiers or []
    ]
    return NamespaceV1(
        name=name,
        delete=delete,
        managedExternalResources=managed_external_resources,
        externalResources=[
            NamespaceTerraformProviderResourceAWSV1(
                provider="aws",
                provisioner=ExternalResourcesProvisionerV1(name=account),
                resources=resources,
            )
        ],
    )


def test_no_duplicates_is_valid() -> None:
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-stage", "acct-stage", s3_identifiers=["bucket-stage"]),
            build_namespace("ns-prod", "acct-prod", s3_identifiers=["bucket-prod"]),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is True


def test_duplicate_across_accounts_is_invalid() -> None:
    """The quayio incident: same identifier copied from stage to prod."""
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-stage", "acct-stage", s3_identifiers=["shared-bucket"]),
            build_namespace("ns-prod", "acct-prod", s3_identifiers=["shared-bucket"]),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is False


def test_duplicate_within_same_account_and_provider_is_valid() -> None:
    """Supported shared-bucket pattern.

    The spec inventory is keyed on (provision_provider, provisioner_name,
    identifier, provider), so duplicates matching on both account and provider
    collapse to one terraform resource and both namespaces receive its output
    secret. Eight of these exist in the bundle today, all under the s3 provider
    (e.g. telemeter-prod-01-default-tenant).
    """
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-a", "acct", s3_identifiers=["shared-bucket"]),
            build_namespace("ns-b", "acct", s3_identifiers=["shared-bucket"]),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is True


def test_duplicate_within_same_account_across_providers_is_invalid() -> None:
    """s3 and s3-cloudfront are separate spec keys, so they do not collapse.

    Both emit aws_s3_bucket under the same terraform address, and terrascript
    keys its resource dict on that address, so the second declaration silently
    overwrites the first's configuration rather than failing.
    """
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-a", "acct", s3_identifiers=["shared-bucket"]),
            build_namespace("ns-b", "acct", cloudfront_identifiers=["shared-bucket"]),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is False


def test_duplicate_across_providers_in_one_namespace_is_invalid() -> None:
    """The same namespace declaring both providers collides just as badly."""
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace(
                "ns",
                "acct",
                s3_identifiers=["shared-bucket"],
                cloudfront_identifiers=["shared-bucket"],
            ),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is False


def test_duplicate_across_s3_and_cloudfront_is_invalid() -> None:
    """Both providers create a real bucket, so they share the global namespace."""
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-a", "acct-a", s3_identifiers=["shared-bucket"]),
            build_namespace("ns-b", "acct-b", cloudfront_identifiers=["shared-bucket"]),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is False


def test_three_accounts_sharing_an_identifier_is_invalid() -> None:
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-a", "acct-a", s3_identifiers=["shared-bucket"]),
            build_namespace("ns-b", "acct-b", s3_identifiers=["shared-bucket"]),
            build_namespace("ns-c", "acct-c", s3_identifiers=["shared-bucket"]),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is False


@pytest.mark.parametrize(
    ("delete", "managed_external_resources"),
    [(True, True), (False, False)],
)
def test_excluded_namespaces_do_not_collide(
    delete: bool, managed_external_resources: bool
) -> None:
    """Namespaces being deleted or with unmanaged resources are not reconciled."""
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-live", "acct-a", s3_identifiers=["shared-bucket"]),
            build_namespace(
                "ns-excluded",
                "acct-b",
                s3_identifiers=["shared-bucket"],
                delete=delete,
                managed_external_resources=managed_external_resources,
            ),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is True


def test_non_bucket_resources_are_ignored() -> None:
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            NamespaceV1(
                name="ns",
                delete=False,
                managedExternalResources=True,
                externalResources=[
                    NamespaceTerraformProviderResourceAWSV1(
                        provider="aws",
                        provisioner=ExternalResourcesProvisionerV1(name="acct"),
                        resources=[
                            NamespaceTerraformResourceAWSV1(provider="rds"),
                            NamespaceTerraformResourceAWSV1(provider="rds"),
                        ],
                    )
                ],
            )
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is True


def test_empty_bundle_is_valid() -> None:
    assert (
        validate_no_duplicate_bucket_names(
            S3BucketNameValidatorQueryData(namespaces=None)
        )
        is True
    )


def test_error_names_identifier_and_both_locations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    query_data = S3BucketNameValidatorQueryData(
        namespaces=[
            build_namespace("ns-stage", "acct-stage", s3_identifiers=["shared-bucket"]),
            build_namespace("ns-prod", "acct-prod", s3_identifiers=["shared-bucket"]),
        ]
    )
    assert validate_no_duplicate_bucket_names(query_data) is False
    assert "shared-bucket" in caplog.text
    assert "acct-stage/s3/ns-stage" in caplog.text
    assert "acct-prod/s3/ns-prod" in caplog.text
