########################################
# Very basic and dirty PoC for querying code-generated types
########################################
from gql_queries.saas_files import saas_files_small_with_provider
from gql_queries.saas_files import saas_files_full
from reconcile.utils import gql


def get_query(query_name: str) -> str:
    with open(f"gql_queries/{query_name}") as f:
        return f.read()


def query_saas_files_small() -> list[saas_files_small_with_provider.SaasFileV2]:
    gqlapi = gql.get_api()
    query = get_query("saas_files/saas_files_small_with_provider.gql")
    data = gqlapi.query(query)

    apps: list[
        saas_files_small_with_provider.AppV1
    ] = saas_files_small_with_provider.data_to_obj(data)
    all_saas_files: list[saas_files_small_with_provider.SaasFileV2] = []
    for app in apps:
        saas_files_v2: list[saas_files_small_with_provider.SaasFileV2] = (
            app.saas_files_v2 or []
        )
        for app_saas_file in saas_files_v2:
            all_saas_files.append(app_saas_file)

    return all_saas_files


def query_saas_files_full() -> list[saas_files_full.SaasFileV2]:
    gqlapi = gql.get_api()
    query = get_query("saas_files/saas_files_full.gql")
    data = gqlapi.query(query)

    apps: list[saas_files_full.AppV1] = saas_files_full.data_to_obj(data)
    all_saas_files: list[saas_files_full.SaasFileV2] = []
    for app in apps:
        saas_files_v2: list[saas_files_full.SaasFileV2] = app.saas_files_v2 or []
        for app_saas_file in saas_files_v2:
            all_saas_files.append(app_saas_file)

    return all_saas_files
