import json
from collections.abc import Mapping

from reconcile.gql_definitions.fragments.aws_organization import (
    AWSOrganization,
)


def get_aws_account_tags(
    organization: AWSOrganization | Mapping | None,
) -> dict[str, str]:
    """
    Get AWS account tags by merging payer account tags

    Args:
        organization: AWSOrganization | Mapping | None - The organization object from which to extract tags.

    Returns:
        dict[str, str]: A dictionary containing the merged tags from the payer account and the account itself.
    """
    if organization is None:
        return {}

    match organization:
        case AWSOrganization():
            payer_account_tags = (
                organization.payer_account.organization_account_tags or {}
            )
            account_tags = organization.tags or {}
        case Mapping():
            payer_account_tags = organization.get("payerAccount", {}).get(
                "organizationAccountTags", {}
            )
            if isinstance(payer_account_tags, str):
                payer_account_tags = json.loads(payer_account_tags)

            account_tags = organization.get("tags", {})
            if isinstance(account_tags, str):
                account_tags = json.loads(account_tags)

    return payer_account_tags | account_tags
