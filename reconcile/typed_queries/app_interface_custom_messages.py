from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.app_interface_custom_messages import (
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from collections.abc import Callable


def get_app_interface_custom_message(
    desired_id: str,
    query_func: Callable | None = None,
) -> str | None:
    """Returns App Interface Custom Message by ID or None if not found"""
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    for item in (
        data.settings[0].custom_messages
        if data.settings and data.settings[0].custom_messages
        else []
    ):
        if item.q_id == desired_id:
            return item.content
    return None
