from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.openshift_resources.settings import (
    AppInterfaceSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError

if TYPE_CHECKING:
    from collections.abc import Callable


def get_openshift_resources_settings(
    query_func: Callable | None = None,
) -> AppInterfaceSettingsV1:
    """Fetch the shared repository URL and secret-backend settings."""
    if query_func is None:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    if data.settings and len(data.settings) == 1:
        return data.settings[0]
    raise AppInterfaceSettingsError("OpenShift resource settings not uniquely defined.")
