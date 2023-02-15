import logging
import sys
from typing import Optional

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
    query,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql


def get_app_interface_vault_settings_optional() -> Optional[AppInterfaceSettingsV1]:
    """Returns App Interface Settings"""
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    if data.vault_settings:
        # assuming a single settings file for now
        return data.vault_settings[0]
    return None


def get_app_interface_vault_settings() -> AppInterfaceSettingsV1:
    """Returns App Interface Settings and exits if none are found"""
    vault_settings = get_app_interface_vault_settings_optional()
    if not vault_settings:
        logging.error("Missing app-interface vault_settings")
        # TODO: We should raise an exception https://issues.redhat.com/browse/APPSRE-7041
        sys.exit(ExitCodes.ERROR)
    return vault_settings
