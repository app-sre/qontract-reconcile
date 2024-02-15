from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.common.app_interface_custom_messages import (
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_app_interface_custom_message(
    desired_id: str,
    query_func: Optional[Callable] = None,
) -> str:
    """Returns App Interface Settings and raises err if none are found"""
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    for item in data.settings[0].custom_messages or []:
        if item.q_id == desired_id:
            return item.content
    raise AppInterfaceSettingsError(f"custom message with id {desired_id} undefined.")
