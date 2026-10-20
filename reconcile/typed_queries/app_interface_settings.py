from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.app_interface_settings import (
    AppInterfaceSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError

if TYPE_CHECKING:
    from collections.abc import Callable


def get_app_interface_settings(
    query_func: Callable | None = None,
) -> AppInterfaceSettingsV1:
    """Returns App Interface settings and raises err if none are found"""
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func)
    if data.settings and len(data.settings) == 1:
        return data.settings[0]
    raise AppInterfaceSettingsError("App Interface settings not uniquely defined.")
