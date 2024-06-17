from reconcile.gql_definitions.terraform_cloudflare_resources.terraform_cloudflare_accounts import (
    CloudflareAccountV1,
    query,
)
from reconcile.utils import gql


def get_cloudflare_accounts() -> list[CloudflareAccountV1]:
    data = query(gql.get_api().query)
    return list(data.accounts or [])
