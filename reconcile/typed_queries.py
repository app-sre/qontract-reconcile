########################################
# Very basic and dirty PoC for querying code-generated types
########################################
from gql_queries.saas_files.saas_files_small_with_provider import (
    data_to_obj,
    AppV1,
    SaasFileV2,
)
from reconcile.utils import gql


def get_query(query_name: str) -> str:
    with open(f"gql_queries/{query_name}") as f:
        return f.read()


def query_saas_files() -> list[SaasFileV2]:
    gqlapi = gql.get_api()
    query = get_query("saas_files/saas_files_small_with_provider.gql")
    data = gqlapi.query(query)

    apps: list[AppV1] = data_to_obj(data)
    all_saas_files: list[SaasFileV2] = []
    for app in apps:
        for app_saas_file in app.saas_files_v2:
            all_saas_files.append(app_saas_file)

    return all_saas_files
