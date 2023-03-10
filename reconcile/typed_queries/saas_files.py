from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.common.saas_files import SaasFileV2
from reconcile.gql_definitions.common.saas_files import query as saas_files_query
from reconcile.gql_definitions.common.saasherder_settings import AppInterfaceSettingsV1
from reconcile.gql_definitions.common.saasherder_settings import (
    query as saasherder_settings_query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError


def get_saas_files(
    name: Optional[str] = None,
    env_name: Optional[str] = None,
    app_name: Optional[str] = None,
    query_func: Optional[Callable] = None,
) -> list[SaasFileV2]:
    if not query_func:
        query_func = gql.get_api().query
    data = saas_files_query(query_func)
    saas_files = list(data.saas_files or [])
    if name is None and env_name is None and app_name is None:
        return saas_files
    if name == "" or env_name == "" or app_name == "":
        return []

    for saas_file in saas_files[:]:
        if name:
            if saas_file.name != name:
                saas_files.remove(saas_file)
                continue

        if env_name:
            for rt in saas_file.resource_templates[:]:
                for target in rt.targets[:]:
                    if target.namespace.environment.name != env_name:
                        rt.targets.remove(target)
                if not rt.targets:
                    saas_file.resource_templates.remove(rt)
            if not saas_file.resource_templates:
                saas_files.remove(saas_file)
                continue

        if app_name:
            if saas_file.app.name != app_name:
                saas_files.remove(saas_file)
                continue

    return saas_files


def get_saasherder_settings(
    query_func: Optional[Callable] = None,
) -> AppInterfaceSettingsV1:
    if not query_func:
        query_func = gql.get_api().query
    if _settings := saasherder_settings_query(query_func).settings:
        return _settings[0]
    raise AppInterfaceSettingsError("settings missing")
