from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_dynatrace_token_provider_token_specs(
    api: GqlApi | None = None,
) -> list[DynatraceTokenProviderTokenSpecV1]:
    api = api if api else gql.get_api()
    data = query(api.query)
    return list(data.token_specs or [])
