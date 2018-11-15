from graphqlclient import GraphQLClient
from reconcile.config import get_config

_gqlapi = None


class GqlApi(object):
    def __init__(self, url, token=None):
        self.url = url
        self.token = token

        self.client = GraphQLClient(self.url)

        if token:
            self.client.inject_token(token)

    def query(self, query):
        return self.client.execute(query)


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
        raise Exception("gql module has not been initialized.")

    return _gqlapi
