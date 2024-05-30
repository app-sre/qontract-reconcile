from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.common.pagerduty_instances import (
    PagerDutyInstanceV1,
    query,
)
from reconcile.utils import gql


def get_pagerduty_instances(
    query_func: Optional[Callable],
) -> list[PagerDutyInstanceV1]:
    """Return all pagerduty instances from app-interface."""
    if not query_func:
        gqlapi = gql.get_api()
        query_func = gqlapi.query
    return query(query_func=query_func).pagerduty_instances or []
