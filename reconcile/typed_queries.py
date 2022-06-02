from typing import Any

from reconcile.gql_queries.ocp import ocp_auth
from reconcile.gql_queries.saas_files import saas_files_small_with_provider
from reconcile.gql_queries.saas_files import saas_files_full
from reconcile.utils import gql


def get_query_data(query_name: str) -> dict[Any, Any]:
    gqlapi = gql.get_api()
    with open(f"reconcile/gql_queries/{query_name}") as f:
        return gqlapi.query(f.read())


def query_saas_files_small() -> list[saas_files_small_with_provider.SaasFileV2]:
    data = get_query_data("saas_files/saas_files_small_with_provider.gql")

    apps: list[saas_files_small_with_provider.AppV1] = (
        saas_files_small_with_provider.ListSaasFilesV2SmallQuery(**data).apps_v1 or []
    )
    all_saas_files: list[saas_files_small_with_provider.SaasFileV2] = []
    for app in apps:
        saas_files_v2: list[saas_files_small_with_provider.SaasFileV2] = (
            app.saas_files or []
        )
        for app_saas_file in saas_files_v2:
            all_saas_files.append(app_saas_file)

    return all_saas_files


def query_saas_files_full() -> list[saas_files_full.SaasFileV2]:
    data = get_query_data("saas_files/saas_files_full.gql")

    apps: list[saas_files_full.AppV1] = (
        saas_files_full.SaasFilesV2FullQuery(**data).apps_v1 or []
    )
    all_saas_files: list[saas_files_full.SaasFileV2] = []
    for app in apps:
        saas_files_v2: list[saas_files_full.SaasFileV2] = app.saas_files or []
        for app_saas_file in saas_files_v2:
            all_saas_files.append(app_saas_file)

    return all_saas_files


def query_ocp_auth() -> list[ocp_auth.OcpReleaseMirrorV1]:
    data = get_query_data("ocp/ocp_auth.gql")
    result: list[ocp_auth.OcpReleaseMirrorV1] = (
        ocp_auth.OCPAuthFullQuery(**data).ocp_release_mirror_v1 or []
    )
    return result
