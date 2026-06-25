from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.dynatrace_token_provider.dynatrace_bootstrap_tokens import (
    DynatraceEnvironmentV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_dynatrace_environments(
    api: GqlApi | None = None,
) -> list[DynatraceEnvironmentV1]:
    api = api or gql.get_api()
    data = query(api.query)
    return list(data.environments or [])
