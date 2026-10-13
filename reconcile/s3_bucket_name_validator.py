import logging
import sys
from collections import defaultdict

from reconcile.gql_definitions.s3_bucket_name_validator import (
    s3_bucket_name_validator,
)
from reconcile.gql_definitions.s3_bucket_name_validator.s3_bucket_name_validator import (
    NamespaceTerraformProviderResourceAWSV1,
    S3BucketNameValidatorQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql

QONTRACT_INTEGRATION = "s3-bucket-name-validator"

# Resource providers whose identifier becomes an S3 bucket name. Both route to
# _populate_tf_resource_s3_bucket() in the terrascript client.
S3_BUCKET_PROVIDERS = frozenset({"s3", "s3-cloudfront"})


def validate_no_duplicate_bucket_names(
    query_data: S3BucketNameValidatorQueryData,
) -> bool:
    """Validate that each S3 bucket identifier maps to exactly one bucket.

    The identifier is used verbatim as the S3 bucket name, so every declaration
    of it must resolve to the same terraform resource. The external resource
    spec inventory is keyed on (provision_provider, provisioner_name,
    identifier, provider), so for a fixed identifier two declarations collapse
    into one resource only when both the account and the resource provider
    match. Anything else produces two resources competing for one bucket name:

    - Different accounts: both try to create the bucket, and whichever applies
      second fails with a 409 BucketAlreadyExists, blocking the shard.
    - Same account, different provider (s3 vs s3-cloudfront): both emit
      aws_s3_bucket under the same terraform address, and terrascript stores
      resources in a dict keyed on that address, so the second declaration
      silently overwrites the first's entire configuration.

    Two namespaces sharing an identifier under the same account *and* provider
    is a supported pattern: the specs collapse to a single terraform resource
    and both namespaces receive its output secret.
    """
    # identifier -> (account, provider) -> namespaces declaring it
    usages: dict[str, dict[tuple[str, str], list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for namespace in query_data.namespaces or []:
        if namespace.delete or not namespace.managed_external_resources:
            continue
        for external_resource in namespace.external_resources or []:
            if not isinstance(
                external_resource, NamespaceTerraformProviderResourceAWSV1
            ):
                continue
            account = external_resource.provisioner.name
            for resource in external_resource.resources:
                if resource.provider in S3_BUCKET_PROVIDERS:
                    usages[resource.identifier][account, resource.provider].append(
                        namespace.name
                    )

    valid = True
    for identifier, specs in sorted(usages.items()):
        if len(specs) > 1:
            valid = False
            locations = sorted(
                f"{account}/{provider}/{namespace_name}"
                for (account, provider), namespace_names in specs.items()
                for namespace_name in namespace_names
            )
            logging.error(
                f"S3 bucket identifier [{identifier}] is declared by "
                f"{len(specs)} distinct external resources: {locations}. The "
                "identifier is used verbatim as the globally unique S3 bucket "
                "name, so it may be declared by only one account and resource "
                "provider."
            )

    return valid


def run(dry_run: bool) -> None:
    query_data = s3_bucket_name_validator.query(query_func=gql.get_api().query)

    if not validate_no_duplicate_bucket_names(query_data):
        sys.exit(ExitCodes.ERROR)
