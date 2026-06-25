from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.dynatrace_token_provider.token_specs import (
    DynatraceTokenProviderTokenSpecV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_dynatrace_token_provider_token_specs(
    api: GqlApi | None = None,
) -> list[DynatraceTokenProviderTokenSpecV1]:
    api = api or gql.get_api()
    data = query(api.query)
    return list(data.token_specs or [])
