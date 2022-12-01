from typing import Optional

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
    query,
)
from reconcile.utils import gql


def get_app_interface_vault_settings() -> Optional[AppInterfaceSettingsV1]:
    """Returns App Interface Settings"""
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    if data.vault_settings:
        # assuming a single settings file for now
        return data.vault_settings[0]
    return None
