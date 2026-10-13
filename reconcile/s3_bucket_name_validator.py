import logging
import sys
from collections import defaultdict

from reconcile.gql_definitions.s3_bucket_name_validator import (
    s3_bucket_name_validator,
)
from reconcile.gql_definitions.s3_bucket_name_validator.s3_bucket_name_validator import (
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceS3CloudFrontV1,
    NamespaceTerraformResourceS3V1,
    S3BucketNameValidatorQueryData,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql

QONTRACT_INTEGRATION = "s3-bucket-name-validator"


def validate_no_duplicate_bucket_names(
    query_data: S3BucketNameValidatorQueryData,
) -> bool:
    """Validate that no S3 bucket identifier is used by more than one AWS account.

    Two namespaces in the *same* account declaring the same identifier is a
    supported pattern: the external resource spec inventory is keyed on
    (provision_provider, provisioner_name, identifier, provider), so the specs
    collapse to a single terraform resource and both namespaces receive its
    output secret.
    """
    usages: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

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
                if isinstance(
                    resource,
                    NamespaceTerraformResourceS3V1
                    | NamespaceTerraformResourceS3CloudFrontV1,
                ):
                    usages[resource.identifier][account].append(namespace.name)

    valid = True
    for identifier, accounts in sorted(usages.items()):
        if len(accounts) > 1:
            valid = False
            locations = sorted(
                f"{account}/{namespace_name}"
                for account, namespace_names in accounts.items()
                for namespace_name in namespace_names
            )
            logging.error(
                f"S3 bucket identifier [{identifier}] is used by "
                f"{len(accounts)} AWS accounts: {locations}. S3 bucket names are "
                "globally unique, so only one account may use this identifier."
            )

    return valid


def run(dry_run: bool) -> None:
    query_data = s3_bucket_name_validator.query(query_func=gql.get_api().query)

    if not validate_no_duplicate_bucket_names(query_data):
        sys.exit(ExitCodes.ERROR)
