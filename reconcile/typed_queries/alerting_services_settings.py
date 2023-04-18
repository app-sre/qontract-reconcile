from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.common.alerting_services_settings import query
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_alerting_services(query_func: Optional[Callable] = None) -> set[str]:
    """Get alertingServices from app-interface settings"""

    if not query_func:
        gqlapi = gql.get_api()
        query_func = gqlapi.query

    data = query(query_func=query_func).settings

    if not data:
        raise AppInterfaceSettingsError("No alerting services labels configured")

    # assuming a single settings file for now
    alerting_services = data[0].alerting_services

    if not alerting_services:
        raise AppInterfaceSettingsError("No alerting services labels configured")

    return set(alerting_services)
