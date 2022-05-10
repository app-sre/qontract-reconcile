########################################
# Very basic and dirty PoC for querying code-generated types
########################################
from code_gen.gen.schema import AppV1, SaasFileV2
import code_gen.gen.saas_files
from reconcile.utils import gql


def get_query(query_name: str) -> str:
    with open(f"code_gen/gql_queries/{query_name}.gql") as f:
        return f.read()


def query_saas_files() -> list[SaasFileV2]:
    gqlapi = gql.get_api()
    query = get_query("saas_files")
    data = gqlapi.query(query)

    apps: list[AppV1] = code_gen.gen.saas_files.data_to_obj(data)
    all_saas_files: list[SaasFileV2] = []
    for app in apps:
        for app_saas_file in app.saas_files_v2:
            all_saas_files.append(app_saas_file)

    return all_saas_files
