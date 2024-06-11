from reconcile.gql_definitions.common.app_interface_dms_settings import (
    DeadMansSnitchSettingsV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.gql import GqlApi


def get_deadmanssnitch_settings(
    gql_api: GqlApi | None = None,
) -> DeadMansSnitchSettingsV1:
    api = gql_api if gql_api else gql.get_api()
    data = query(query_func=api.query)
    if data.settings and data.settings[0].dead_mans_snitch_settings is not None:
        return data.settings[0].dead_mans_snitch_settings
    raise AppInterfaceSettingsError("deadmanssnitch settings missing")
