import logging
import textwrap

from reconcile.utils.qontract_server_client import QontractServerClient
from reconcile.utils.config import get_config
from reconcile.status import RunningState


_gqlapi = None


INTEGRATIONS_QUERY = """
{
    integrations: integrations_v1 {
        name
        description
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
        super().__init__(
            "Error getting resource from path {}: {}".format(path, str(msg))
        )


class GqlApi:
    _valid_schemas = None
    _queried_schemas = set()

    def __init__(self, url, token=None, int_name=None, validate_schemas=False,
                 use_sessions=False, sha_url=False):
        self.url = url
        self.token = token
        self.integration = int_name
        self.validate_schemas = validate_schemas
        self.client = QontractServerClient(
            self.url, token=token, use_sessions=use_sessions, sha_url=sha_url)

        if validate_schemas and not int_name:
            raise Exception('Cannot validate schemas if integration name '
                            'is not supplied')

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
            result = self.client.query(query, variables)
        except Exception as e:
            raise GqlApiError(
                'Could not connect to GraphQL server ({})'.format(e))

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
            # Do not validate schema in resources since schema support in the
            # resources is not complete.
            resources = self.query(query, {'path': path},
                                   skip_validation=True)['resources']
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


def init_from_config(sha_url=True, integration=None, validate_schemas=False,
                     print_url=True, use_sessions=True):
    """Inits the GraphQL client based on the server url and token defined in the
    config. This method is a wrapper around `init`.


    :param sha_url: use the /graphqlsha/<sha> endpoint, defaults to True
    :type sha_url: bool, optional
    :param integration: name of the integration, required if validate_schemas
    :type integration: [description], defaults to None
    :param validate_schemas: raise error if non defined schemas are queried,
        defaults to False
    :type validate_schemas: bool, optional
    :param print_url: when a new sha is acquired, it will be printed,
        defaults to True
    :type print_url: bool, optional
    :param use_sessions: reuse session for all the requests performed.
        defaults to True
    :type use_sessions: bool, optional
    """

    config = get_config()
    server = config['graphql']['server']
    token = config['graphql'].get('token')
    return init(server, token=token, sha_url=sha_url, integration=integration,
                validate_schemas=validate_schemas, print_url=print_url,
                use_sessions=use_sessions)


def init(url, token=None, sha_url=True, integration=None,
         validate_schemas=False, print_url=True, use_sessions=True):
    """Inits the GraphQL client


    :param url: Qontract Server url
    :type url: str
    :param token: authorization header, typically: `Bearer <user:pass|base64>`
    :type token: str, optional
    :param sha_url: use the /graphqlsha/<sha> endpoint, defaults to True
    :type sha_url: bool, optional
    :param integration: name of the integration, required if validate_schemas
    :type integration: [description], defaults to None
    :param validate_schemas: raise error if non defined schemas are queried,
        defaults to False
    :type validate_schemas: bool, optional
    :param print_url: when a new sha is acquired, it will be printed,
        defaults to True
    :type print_url: bool, optional
    :param use_sessions: reuse session for all the requests performed.
        defaults to True
    :type use_sessions: bool, optional

    """
    global _gqlapi
    _gqlapi = GqlApi(url, token, integration, validate_schemas,
                     sha_url=sha_url, use_sessions=use_sessions)

    if print_url:
        url = _gqlapi.client.query_url
        logging.info(f'using gql endpoint {url}')

    if sha_url:
        runing_state = RunningState()
        git_commit_info = _gqlapi.client.get_git_commit_info()
        runing_state.timestamp = git_commit_info.get('timestamp')
        runing_state.commit = git_commit_info.get('commit')

    return _gqlapi


def get_api():
    global _gqlapi

    if not _gqlapi:
        raise GqlApiError("gql module has not been initialized.")

    return _gqlapi
