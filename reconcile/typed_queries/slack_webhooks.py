from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.slack_webhooks.slack_webhooks import (
    SlackWorkspaceV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from collections.abc import Callable


def get_slack_webhooks(query_func: Callable | None = None) -> list[SlackWorkspaceV1]:
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    return list(data.slack_workspaces or [])
