import time
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
)
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from pydantic import BaseModel
from pydantic.error_wrappers import ValidationError
from pytest_httpserver import HTTPServer

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gql import GqlApi
from reconcile.utils.models import data_default_none
from reconcile.utils.state import State


@pytest.fixture
def patch_sleep(mocker):
    yield mocker.patch.object(time, "sleep")


@pytest.fixture
def secret_reader(mocker) -> None:
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.read.return_value = "secret"
    mock_secretreader.read_secret.return_value = "secret"
    return mock_secretreader


@pytest.fixture
def s3_state_builder() -> Callable[[Mapping], State]:
    """
    Example input data:
    {
        "get": {
            # This maps data being returned by get
            "path/to/item": {
                "some_key": "content",
                "other_content": "content",
            },
            "other/path": {
                "other": "data",
            },
        },
        "ls": [
            "/path/item1",
            "/path/item2",
        ]
    }
    """

    def builder(data: Mapping) -> State:
        def get(key: str, *args) -> dict:
            try:
                return data["get"][key]
            except KeyError:
                if args:
                    return args[0]
                raise

        def __getitem__(self, key: str) -> dict:
            return get(key)

        state = create_autospec(spec=State)
        mock_get = MagicMock(side_effect=get)
        state.get = mock_get
        state.__getitem__ = __getitem__
        state.ls.side_effect = [data.get("ls", [])]
        return state

    return builder


@pytest.fixture
def vault_secret():
    return VaultSecret(
        path="path/test",
        field="key",
        format=None,
        version=None,
    )


@pytest.fixture
def data_factory() -> (
    Callable[
        [type[BaseModel], MutableMapping[str, Any] | None],
        MutableMapping[str, Any],
    ]
):
    """Set default values to None."""

    def _data_factory(
        klass: type[BaseModel], data: MutableMapping[str, Any] | None = None
    ) -> MutableMapping[str, Any]:
        return data_default_none(klass, data or {})

    return _data_factory


class GQLClassFactoryError(Exception):
    pass


@pytest.fixture
def gql_class_factory() -> (
    Callable[
        [type[BaseModel], MutableMapping[str, Any] | None],
        BaseModel,
    ]
):
    """Create a GQL class from a fixture and set default values to None."""

    def _gql_class_factory(
        klass: type[BaseModel], data: MutableMapping[str, Any] | None = None
    ) -> BaseModel:
        try:
            return klass(**data_default_none(klass, data or {}))
        except ValidationError as e:
            msg = "[gql_class_factory] Your given data does not match the class ...\n"
            msg += "\n".join([str(m) for m in list(e.raw_errors)])
            raise GQLClassFactoryError(msg) from e

    return _gql_class_factory


@pytest.fixture
def gql_api_builder() -> Callable[[Mapping | None], GqlApi]:
    def builder(data: Mapping | None = None) -> GqlApi:
        gql_api = create_autospec(GqlApi)
        gql_api.query.return_value = data
        return gql_api

    return builder


@pytest.fixture
def set_httpserver_responses_based_on_fixture(httpserver: HTTPServer) -> Callable:
    """Create httpserver responses based fixture files."""

    def _(fx: Fixtures, paths: Iterable[str]) -> None:
        for path in paths:
            for method in ["get", "post", "put", "patch", "delete"]:
                method_file = Path(fx.path(path.lstrip("/"))) / f"{method}.json"
                if method_file.exists():
                    httpserver.expect_oneshot_request(
                        path, method=method
                    ).respond_with_data(
                        method_file.read_text(), content_type="text/json"
                    )

    return _
