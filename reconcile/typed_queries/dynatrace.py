from reconcile.gql_definitions.dynatrace_token_provider.dynatrace_bootstrap_tokens import (
    DynatraceEnvironmentV1,
    query,
)
from reconcile.utils import gql


def get_dynatrace_environments() -> list[DynatraceEnvironmentV1]:
    data = query(gql.get_api().query)
    return list(data.environments or [])
