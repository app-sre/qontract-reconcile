import json

from graphqlclient import GraphQLClient
from reconcile.config import get_config

_gqlapi = None


class GqlApiError(Exception):
    pass


class GqlApi(object):
    def __init__(self, url, token=None):
        self.url = url
        self.token = token

        self.client = GraphQLClient(self.url)

        if token:
            self.client.inject_token(token)

    def query(self, query, variables=None):
        result_json = self.client.execute(query, variables)
        result = json.loads(result_json)

        if 'errors' in result:
            raise GqlApiError(result['errors'])

        if 'data' not in result:
            raise GqlApiError((
                "`data` field missing from GraphQL"
                "server response."))

        return result['data']

    def get_resource(self, path):
        query = """
        query Resource($path: String) {
            resources(path: $path) {
                path
                content
                sha256sum
            }
        }
        """

        resources = self.query(query, {'path': path})['resources']

        if len(resources) != 1:
            raise GqlApiError('Expecting one and only one resource.')

        return resources[0]


def init(url, token=None):
    global _gqlapi
    _gqlapi = GqlApi(url, token)
    return _gqlapi


def init_from_config():
    config = get_config()

    server = config['graphql']['server']
    token = config['graphql'].get('token')

    return init(server, token)


def get_api():
    global _gqlapi

    if not _gqlapi:
        raise GqlApiError("gql module has not been initialized.")

    return _gqlapi
