from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.app_quay_repos_escalation_policies import (
    AppV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_apps_quay_repos_escalation_policies(
    gql_api: GqlApi | None = None,
) -> list[AppV1]:
    api = gql_api or gql.get_api()
    data = query(query_func=api.query)
    return list(data.apps or [])
