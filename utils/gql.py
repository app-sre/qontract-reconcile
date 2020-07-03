import json
import requests
import os
import contextlib

from graphqlclient import GraphQLClient
from utils.config import get_config

_gqlapi = None


class GqlApiError(Exception):
    pass


class GqlApiIntegrationNotFound(Exception):
    def __init__(self, integration):
        super().__init__(f"integration not found: {integration}")


class GqlApiErrorForbiddenSchema(Exception):
    def __init__(self, schema):
        super().__init__(f"forbidden schema: {schema}")


class GqlGetResourceError(Exception):
    def __init__(self, path, msg):
        super(GqlGetResourceError, self).__init__(
            "error getting resource from path {}: {}".format(path, str(msg))
        )


INTEGRATIONS_QUERY = """
{
    integrations_v1 {
        name
        schemas
    }
}
"""


class GqlApi(object):
    _called_schemas = set([])
    _valid_schemas = None

    def __init__(self, url, token=None, int_name=None):
        self.url = url
        self.token = token
        self.integration = int_name

        self.client = GraphQLClient(self.url)

        if token:
            self.client.inject_token(token)

        if int_name:
            integrations = self.query(INTEGRATIONS_QUERY)

            for integration in integrations['integrations_v1']:
                if integration['name'] == int_name:
                    self._valid_schemas = integration['schemas']
                    break

            # TODO: uncomment in the future, but for now let's allow
            # integrations that are not declared in app-interface
            # if self._valid_schemas is None:
            #     raise GqlApiIntegrationNotFound(int_name)

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

        schemas = result.get('extensions', {}).get('schemas', None)
        if schemas:
            self._called_schemas.update(schemas)
            if self._valid_schemas:
                for schema in schemas:
                    if schema not in self._valid_schemas:
                        raise GqlApiErrorForbiddenSchema(schema)

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
            raise GqlGetResourceError(
                path,
                'Resource not found.')

        if len(resources) != 1:
            raise GqlGetResourceError(
                path,
                'Expecting one and only one resource.')

        return resources[0]


def init(url, token=None, integration=None):
    global _gqlapi
    _gqlapi = GqlApi(url, token, integration)
    return _gqlapi


def get_sha_url(server, token=None):
    sha_endpoint = server.replace('graphql', 'sha256')
    headers = {'Authorization': token} if token else None
    r = requests.get(sha_endpoint, headers=headers)
    sha = r.content.decode('utf-8')
    gql_sha_endpoint = server.replace('graphql', 'graphqlsha')
    return f'{gql_sha_endpoint}/{sha}'


def init_from_config(sha_url=True, integration=None):
    config = get_config()

    server = config['graphql']['server']
    token = config['graphql'].get('token')
    if sha_url:
        server = get_sha_url(server, token)

    return init(server, token, integration)


def get_api():
    global _gqlapi

    if not _gqlapi:
        raise GqlApiError("gql module has not been initialized.")

    return _gqlapi


def get_called_schemas():
    global _gqlapi
    return list(_gqlapi._called_schemas)


def clear_called_schemas():
    global _gqlapi
    _gqlapi._called_schemas = set([])
