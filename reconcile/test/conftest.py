import time
from collections.abc import (
    Callable,
    MutableMapping,
)
from typing import (
    Any,
    Optional,
)

import httpretty as _httpretty
import pytest
from pydantic import BaseModel

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


@pytest.fixture
def patch_sleep(mocker):
    yield mocker.patch.object(time, "sleep")


@pytest.fixture()
def httpretty():
    with _httpretty.enabled(allow_net_connect=False):
        _httpretty.reset()
        yield _httpretty


@pytest.fixture
def secret_reader(mocker) -> None:
    mock_secretreader = mocker.patch(
        "reconcile.utils.secret_reader.SecretReader", autospec=True
    )
    mock_secretreader.read.return_value = "secret"
    mock_secretreader.read_secret.return_value = "secret"
    return mock_secretreader


@pytest.fixture
def vault_secret():
    return VaultSecret(
        path="path/test",
        field="key",
        format=None,
        version=None,
    )


def data_default_none(
    klass: type[BaseModel], data: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Set default values to None for required but optional fields."""
    for field in klass.__fields__.values():
        if not field.required:
            continue

        if field.alias not in data:
            if field.allow_none:
                data[field.alias] = None
        else:
            if isinstance(field.type_, type) and issubclass(field.type_, BaseModel):
                if isinstance(data[field.alias], dict):
                    data[field.alias] = data_default_none(
                        field.type_, data[field.alias]
                    )
                if isinstance(data[field.alias], list):
                    data[field.alias] = [
                        data_default_none(field.type_, item)
                        for item in data[field.alias]
                    ]

    return data


@pytest.fixture
def data_factory() -> Callable[
    [type[BaseModel], MutableMapping[str, Any]], MutableMapping[str, Any]
]:
    """Set default values to None."""

    def _data_factory(
        klass: type[BaseModel], data: MutableMapping[str, Any] = {}
    ) -> MutableMapping[str, Any]:
        return data_default_none(klass, data)

    return _data_factory


@pytest.fixture
def gql_class_factory() -> Callable[
    [type[BaseModel], Optional[MutableMapping[str, Any]]], BaseModel
]:
    """Create a GQL class from a fixture and set default values to None."""

    def _gql_class_factory(
        klass: type[BaseModel], data: Optional[MutableMapping[str, Any]] = None
    ) -> BaseModel:
        return klass(**data_default_none(klass, data or {}))

    return _gql_class_factory
