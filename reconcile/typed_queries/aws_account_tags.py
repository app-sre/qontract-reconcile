from reconcile.gql_definitions.fragments.aws_organization import (
    AWSOrganization,
)


def get_aws_account_tags(organization: AWSOrganization | None) -> dict[str, str]:
    """
    Get AWS account tags by merging payer account tags

    Args:
        organization: AWSOrganization | None - The organization object from which to extract tags.

    Returns:
        dict[str, str]: A dictionary containing the merged tags from the payer account and the account itself.
    """
    if organization is None:
        return {}
    payer_account_tags = organization.payer_account.organization_account_tags or {}
    account_tags = organization.tags or {}
    return payer_account_tags | account_tags
