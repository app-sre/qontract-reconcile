########################################
# Very basic and dirty PoC for querying code-generated types
########################################
from schema.qontract_schema import App_v1, SaasFile_v2
from schema.saas_file_query import Operations as saas_file_operations

# TODO: remove type ignore
from sgqlc.endpoint.http import HTTPEndpoint  # type: ignore[import]

from reconcile.utils.config import get_config
from urllib.parse import urlparse


_endpoint = None


def _get_endpoint():
    global _endpoint
    if _endpoint:
        return _endpoint

    config = get_config()
    server_url = urlparse(config["graphql"]["server"])
    server = server_url.geturl()
    token = config["graphql"].get("token")
    headers = {}
    if token:
        headers["Authorization"] = token
    _endpoint = HTTPEndpoint(server, headers)
    return _endpoint


def query_saas_files() -> list[SaasFile_v2]:
    # Query defined in saas_files_query.gql
    op = saas_file_operations.query.list_saas_files_v2

    # Query the data
    data = _get_endpoint()(op)

    # Bring data into desired format - there is probably a more elegant way to do this
    apps: list[App_v1] = (op + data).apps
    all_saas_files: list[SaasFile_v2] = []
    for app in apps:
        for app_saas_file in app.saas_files_v2:
            all_saas_files.append(app_saas_file)

    return all_saas_files
