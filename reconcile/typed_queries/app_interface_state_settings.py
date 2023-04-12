from typing import Optional

from reconcile.gql_definitions.common.app_interface_state_settings import (
    AppInterfaceStateConfigurationV1,
    query,
)
from reconcile.utils import gql


def get_app_interface_state_settings() -> Optional[AppInterfaceStateConfigurationV1]:
    """Returns App Interface Settings"""
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    if data.settings and len(data.settings) > 0:
        return data.settings[0].state

    return None
