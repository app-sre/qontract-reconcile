import logging
import textwrap
import threading
from datetime import (
    UTC,
    datetime,
)
from typing import Any
from urllib.parse import urlparse

import requests
from gql import (
    Client,
    gql,
)
from gql.transport.exceptions import TransportQueryError
from gql.transport.requests import RequestsHTTPTransport
from gql.transport.requests import log as requests_logger
from requests.auth import AuthBase
from requests.cookies import RequestsCookieJar
from sentry_sdk import capture_exception
from sretoolbox.utils import retry

from reconcile.status import RunningState
from reconcile.utils.config import get_config

INTEGRATIONS_QUERY = """
{
    integrations: integrations_v1 {
        name
        description
        schemas
    }
}
"""

requests_logger.setLevel(logging.WARNING)


def capture_and_forget(error):
    """fire-and-forget an exception to sentry

    :param error: exception to be captured and sent to sentry
    :type error: Exception
    """

    try:
        capture_exception(error)
    except Exception:
        pass


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
        super().__init__(f"Error getting resource from path {path}: {str(msg)}")


class GqlApi:
    _valid_schemas: list[str] = []
    _queried_schemas: set[Any] = set()

    def __init__(
        self,
        url: str,
        token: str | None = None,
        int_name=None,
        validate_schemas=False,
        commit: str | None = None,
        commit_timestamp: str | None = None,
    ) -> None:
        self.url = url
        self.token = token
        self.integration = int_name
        self.validate_schemas = validate_schemas
        self.commit = commit
        self.commit_timestamp = commit_timestamp
        self.client = self._init_gql_client()

        if validate_schemas and not int_name:
            raise Exception(
                "Cannot validate schemas if integration name is not supplied"
            )

        if int_name:
            integrations = self.query(INTEGRATIONS_QUERY, skip_validation=True)

            for integration in integrations["integrations"]:
                if integration["name"] == int_name:
                    self._valid_schemas = integration["schemas"]
                    break

            if validate_schemas and not self._valid_schemas:
                raise GqlApiIntegrationNotFound(int_name)

    def _init_gql_client(self) -> Client:
        req_headers = None
        if self.token:
            # The token stored in vault is already in the format 'Basic ...'
            req_headers = {"Authorization": self.token}
        transport = PersistentRequestsHTTPTransport(
            requests.Session(), self.url, headers=req_headers, timeout=30
        )
        return Client(transport=transport)

    def close(self):
        logging.debug("Closing GqlApi client")
        if self.client.transport.session:
            self.client.transport.session.close()

    @retry(exceptions=GqlApiError, max_attempts=5, hook=capture_and_forget)
    def query(
        self, query: str, variables=None, skip_validation=False
    ) -> dict[str, Any] | None:
        try:
            result = self.client.execute(
                gql(query), variables, get_execution_result=True
            ).formatted
        except requests.exceptions.ConnectionError as e:
            raise GqlApiError(f"Could not connect to GraphQL server ({e})")
        except TransportQueryError as e:
            raise GqlApiError(f"`error` returned with GraphQL response {e}")
        except AssertionError:
            raise GqlApiError("`data` field missing from GraphQL response payload")
        except Exception as e:
            raise GqlApiError("Unexpected error occurred") from e

        # show schemas if log level is debug
        query_schemas = result.get("extensions", {}).get("schemas", [])
        self._queried_schemas.update(query_schemas)

        for s in query_schemas:
            logging.debug(["schema", s])

        if self.validate_schemas and not skip_validation:
            forbidden_schemas = [
                schema for schema in query_schemas if schema not in self._valid_schemas
            ]
            if forbidden_schemas:
                raise GqlApiErrorForbiddenSchema(forbidden_schemas)

        # This is to appease mypy. This exception won't be thrown as this condition
        # is already handled above with AssertionError
        if result["data"] is None:
            raise GqlApiError("`data` not received in GraphQL payload")

        return result["data"]

    def get_template(self, path: str) -> dict[str, str]:
        query = """
        query Template($path: String) {
          templates: template_v1(path: $path) {
            path
            template
          }
        }
        """

        try:
            templates = []
            q_result = self.query(query, {"path": path})
            if q_result:
                templates = q_result["templates"]
        except GqlApiError:
            raise GqlGetResourceError(path, "Template not found.")

        if len(templates) != 1:
            raise GqlGetResourceError(path, "Expecting one and only one template.")

        return templates[0]

    def get_resource(self, path: str) -> dict[str, Any]:
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
            resources = self.query(query, {"path": path}, skip_validation=True)[
                "resources"
            ]
        except GqlApiError:
            raise GqlGetResourceError(path, "Resource not found.")

        if len(resources) != 1:
            raise GqlGetResourceError(path, "Expecting one and only one resource.")

        return resources[0]

    def get_resources_by_schema(self, schema: str) -> list[dict[str, str]]:
        """Return all resources (resources_v1) filtered by given schema."""
        query = """
        query Resource($schema: String) {
            resources: resources_v1 (schema: $schema) {
                path
                content
                sha256sum
            }
        }
        """

        # Do not validate schema in resources since schema support in the
        # resources is not complete.
        resources = self.query(query, {"schema": schema}, skip_validation=True)
        return resources["resources"]

    def get_queried_schemas(self):
        return list(self._queried_schemas)

    @property
    def commit_timestamp_utc(self) -> str | None:
        if self.commit_timestamp:
            return datetime.fromtimestamp(int(self.commit_timestamp), UTC).isoformat()
        return None


class GqlApiSingleton:
    gql_api: GqlApi | None = None
    gqlapi_lock = threading.Lock()

    @classmethod
    def create(cls, *args, **kwargs) -> GqlApi:
        with cls.gqlapi_lock:
            if cls.gql_api:
                logging.debug("Resestting GqlApi instance")
                cls.close_gqlapi()
            cls.gql_api = GqlApi(*args, **kwargs)
        return cls.gql_api

    @classmethod
    def close_gqlapi(cls):
        cls.gql_api.close()

    @classmethod
    def instance(cls) -> GqlApi:
        if not cls.gql_api:
            raise GqlApiError("gql module has not been initialized.")
        return cls.gql_api

    @classmethod
    def close(cls) -> None:
        with cls.gqlapi_lock:
            if cls.gql_api:
                cls.close_gqlapi()
                cls.gql_api = None


def init(
    url: str,
    token: str | None = None,
    integration=None,
    validate_schemas=False,
    commit: str | None = None,
    commit_timestamp: str | None = None,
):
    return GqlApiSingleton.create(
        url,
        token,
        integration,
        validate_schemas,
        commit=commit,
        commit_timestamp=commit_timestamp,
    )


def get_resource(path: str) -> dict[str, Any]:
    return get_api().get_resource(path)


class PersistentRequestsHTTPTransport(RequestsHTTPTransport):
    """A transport for the GQL Client that uses an existing.
    Is a reduced version of the RequestsHTTPTransport class from gql library
    with the connect and close methods removed, cause they are implemented
    to disconnect after each query.
    """

    def __init__(
        self,
        session: requests.Session,
        url: str,
        headers: dict[str, Any] | None = None,
        cookies: dict[str, Any] | RequestsCookieJar | None = None,
        auth: AuthBase | None = None,
        use_json: bool = True,
        timeout: int | None = None,
        verify: bool | str = True,
        retries: int = 0,
        method: str = "POST",
        **kwargs: Any,
    ):
        super().__init__(
            url,
            headers,
            cookies,
            auth,
            use_json,
            timeout,
            verify,
            retries,
            method,
            **kwargs,
        )
        # can't directly assign, due to mypy type checking
        self.session = session  # type: ignore

    def connect(self):
        pass

    def close(self) -> None:
        pass


@retry(exceptions=requests.exceptions.HTTPError, max_attempts=5)
def get_sha(server, token=None):
    sha_endpoint = server._replace(path="/sha256")
    headers = {"Authorization": token} if token else None
    response = requests.get(sha_endpoint.geturl(), headers=headers, timeout=60)
    response.raise_for_status()
    sha = response.content.decode("utf-8")
    return sha


@retry(exceptions=requests.exceptions.HTTPError, max_attempts=5)
def get_git_commit_info(sha, server, token=None):
    git_commit_info_endpoint = server._replace(path=f"/git-commit-info/{sha}")
    headers = {"Authorization": token} if token else None
    response = requests.get(
        git_commit_info_endpoint.geturl(), headers=headers, timeout=60
    )
    response.raise_for_status()
    git_commit_info = response.json()
    return git_commit_info


@retry(exceptions=requests.exceptions.ConnectionError, max_attempts=5)
def init_from_config(
    autodetect_sha=True,
    sha=None,
    integration=None,
    validate_schemas=False,
    print_url=True,
):
    server, token, commit, timestamp = _get_gql_server_and_token(
        autodetect_sha=autodetect_sha, sha=sha
    )

    if print_url:
        logging.info(f"using gql endpoint {server}")
    return init(
        server,
        token,
        integration,
        validate_schemas,
        commit=commit,
        commit_timestamp=timestamp,
    )


def _get_gql_server_and_token(
    autodetect_sha: bool = False, sha: str | None = None
) -> tuple[str, str, str | None, str | None]:
    config = get_config()

    server_url = urlparse(config["graphql"]["server"])
    server = server_url.geturl()
    token = config["graphql"].get("token")
    if sha:
        server = server_url._replace(path=f"/graphqlsha/{sha}").geturl()
    elif autodetect_sha:
        sha = get_sha(server_url, token)
        server = server_url._replace(path=f"/graphqlsha/{sha}").geturl()
    if sha:
        running_state = RunningState()
        git_commit_info = get_git_commit_info(sha, server_url, token)
        running_state.timestamp = git_commit_info.get("timestamp")  # type: ignore[attr-defined]
        running_state.commit = git_commit_info.get("commit")  # type: ignore[attr-defined]
        return server, token, running_state.commit, running_state.timestamp

    return server, token, None, None


def get_api() -> GqlApi:
    return GqlApiSingleton.instance()


def get_api_for_sha(
    sha: str, integration: str | None = None, validate_schemas: bool = True
) -> GqlApi:
    server, token, commit, timestamp = _get_gql_server_and_token(
        autodetect_sha=False, sha=sha
    )
    return GqlApi(
        server,
        token,
        integration,
        validate_schemas,
        commit=commit,
        commit_timestamp=timestamp,
    )


def get_api_for_server(
    server: str,
    token: str | None,
    integration: str | None = None,
    validate_schemas: bool = True,
) -> GqlApi:
    return GqlApi(
        server,
        token,
        integration,
        validate_schemas,
        commit=None,
        commit_timestamp=None,
    )


@retry(exceptions=requests.exceptions.HTTPError, max_attempts=5)
def get_diff(
    old_sha: str, file_type: str | None = None, file_path: str | None = None
) -> dict[str, Any]:
    config = get_config()

    server_url = urlparse(config["graphql"]["server"])
    token = config["graphql"].get("token")
    current_sha = get_sha(server_url, token)
    logging.debug(f"get bundle diffs between {old_sha} and {current_sha}...")
    if file_type and file_path:
        if not file_path.startswith("/"):
            file_path = f"/{file_path}"
        diff_endpoint = server_url._replace(
            path=f"/diff/{old_sha}/{current_sha}/{file_type}{file_path}"
        )
    else:
        diff_endpoint = server_url._replace(path=f"/diff/{old_sha}/{current_sha}")
    headers = {"Authorization": token} if token else None
    response = requests.get(diff_endpoint.geturl(), headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()
