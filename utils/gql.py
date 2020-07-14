import json
import requests
import os
import contextlib
import textwrap
import logging

from graphqlclient import GraphQLClient
from utils.config import get_config

_gqlapi = None


INTEGRATIONS_QUERY = """
{
    integrations: integrations_v1 {
        name
        schemas
    }
}
"""


class GqlApiError(Exception):
    pass


class GqlApiIntegrationNotFound(Exception):
    def __init__(self, integration):
        msg = f"""
        Integration not found: {integration}

        Integration should be defined in App-Interface with the
        /app-sre/integration-1.yml schema.
        """
        super().__init__(textwrap.dedent(msg).strip())


class GqlApiErrorForbiddenSchema(Exception):
    def __init__(self, schemas):
        msg = f"""
        Forbidden schemas: {schemas}

        The `schemas` parameter in the integration file in App-Interface
        should be updated to include these schemas.
        """
        super().__init__(textwrap.dedent(msg).strip())


class GqlGetResourceError(Exception):
    def __init__(self, path, msg):
        super(GqlGetResourceError, self).__init__(
            "Error getting resource from path {}: {}".format(path, str(msg))
        )


class GqlApi(object):
    _valid_schemas = None
    _queried_schemas = set()

    def __init__(self, url, token=None, int_name=None, validate_schemas=False):
        self.url = url
        self.token = token
        self.integration = int_name
        self.validate_schemas = validate_schemas
        self.client = GraphQLClient(self.url)

        if validate_schemas and not int_name:
            raise Exception('Cannot validate schemas if integration name '
                            'is not supplied')

        if token:
            self.client.inject_token(token)

        if int_name:
            integrations = self.query(INTEGRATIONS_QUERY, skip_validation=True)

            for integration in integrations['integrations']:
                if integration['name'] == int_name:
                    self._valid_schemas = integration['schemas']
                    break

            if not self._valid_schemas:
                raise GqlApiIntegrationNotFound(int_name)

    def query(self, query, variables=None, skip_validation=False):
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

        # show schemas if log level is debug
        query_schemas = result.get('extensions', {}).get('schemas', [])
        self._queried_schemas.update(query_schemas)

        for s in query_schemas:
            logging.debug(['schema', s])

        if self.validate_schemas and not skip_validation:
            forbidden_schemas = [schema for schema in query_schemas
                                 if schema not in self._valid_schemas]
            if forbidden_schemas:
                raise GqlApiErrorForbiddenSchema(forbidden_schemas)

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

    def get_queried_schemas(self):
        return list(self._queried_schemas)


def init(url, token=None, integration=None, validate_schemas=False):
    global _gqlapi
    _gqlapi = GqlApi(url, token, integration, validate_schemas)
    return _gqlapi


def get_sha_url(server, token=None):
    sha_endpoint = server.replace('graphql', 'sha256')
    headers = {'Authorization': token} if token else None
    r = requests.get(sha_endpoint, headers=headers)
    sha = r.content.decode('utf-8')
    gql_sha_endpoint = server.replace('graphql', 'graphqlsha')
    return f'{gql_sha_endpoint}/{sha}'


def init_from_config(sha_url=True, integration=None, validate_schemas=False):
    config = get_config()

    server = config['graphql']['server']
    token = config['graphql'].get('token')
    if sha_url:
        server = get_sha_url(server, token)

    return init(server, token, integration, validate_schemas)


def get_api():
    global _gqlapi

    if not _gqlapi:
        raise GqlApiError("gql module has not been initialized.")

    return _gqlapi
