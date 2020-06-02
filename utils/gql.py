import json
import requests
import os
import contextlib

from graphqlclient import GraphQLClient
from utils.config import get_config

_gqlapi = None


class GqlApiError(Exception):
    pass


class GqlGetResourceError(Exception):
    def __init__(self, path, msg):
        super(GqlGetResourceError, self).__init__(
            "error getting resource from path {}: {}".format(path, str(msg))
        )


class GqlApi(object):
    _resource_cache = None

    def __init__(self, url, token=None, cache_resources=False):
        self.url = url
        self.token = token
        self.cache_resources = cache_resources

        self.client = GraphQLClient(self.url)

        if token:
            self.client.inject_token(token)

    def query(self, query, variables=None):
        try:
            # supress print on HTTP error
            # https://github.com/prisma-labs/python-graphql-client
            # /blob/master/graphqlclient/client.py#L32-L33
            with open(os.devnull, 'w') as f, contextlib.redirect_stdout(f):
                result_json = self.client.execute(query, variables)
        except Exception as e:
            raise GqlApiError(
                'Could not connect to GraphQL server ({})'.format(e))

        result = json.loads(result_json)

        if 'errors' in result:
            raise GqlApiError(result['errors'])

        if 'data' not in result:
            raise GqlApiError((
                "`data` field missing from GraphQL"
                "server response."))

        return result['data']

    def get_resource(self, path):
        if self.cache_resources:
            try:
                resource = self.get_resource_cache()[path]
            except KeyError:
                raise GqlGetResourceError(path, 'Resource not found.')
        else:
            resource = self._do_get_resource(path)

        return resource

    def _do_get_resource(self, path):
        query = """
        query Resource($path: String) {
            resources: resources_v1 (path: $path) {
                path
                content
                sha256sum
            }
        }
        """

        try:
            resources = self.query(query, {'path': path})['resources']
        except GqlApiError as e:
            if '409' in str(e):
                raise e
            raise GqlGetResourceError(path, 'Resource not found.')

        if len(resources) != 1:
            raise GqlGetResourceError(path,
                                      'Expecting one and only one resource.')

        return resources[0]

    def get_resource_cache(self):
        if not self._resource_cache:
            data = self.query("{ resources_v1 { path content sha256sum }}")
            resources = data['resources_v1']
            self._resource_cache = {r['path']: r for r in resources}

        return self._resource_cache


def init(url, token=None, cache_resources=False):
    global _gqlapi
    _gqlapi = GqlApi(url, token, cache_resources)
    return _gqlapi


def get_sha_url(server, token=None):
    sha_endpoint = server.replace('graphql', 'sha256')
    headers = {'Authorization': token} if token else None
    r = requests.get(sha_endpoint, headers=headers)
    sha = r.content.decode('utf-8')
    gql_sha_endpoint = server.replace('graphql', 'graphqlsha')
    return f'{gql_sha_endpoint}/{sha}'


def init_from_config(sha_url=True, cache_resources=False):
    config = get_config()

    server = config['graphql']['server']
    token = config['graphql'].get('token')
    if sha_url:
        server = get_sha_url(server, token)

    return init(server, token, cache_resources)


def get_api():
    global _gqlapi

    if not _gqlapi:
        raise GqlApiError("gql module has not been initialized.")

    return _gqlapi
