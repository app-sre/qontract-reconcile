from pathlib import Path
from typing import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.templating.template_collection import (
    TemplateCollectionVariablesV1,
)
from reconcile.templating.renderer import (
    LocalFilePersistence,
    join_path,
    unpack_dynamic_variables,
    unpack_static_variables,
)


@pytest.fixture
def collection_variables(gql_class_factory: Callable) -> TemplateCollectionVariablesV1:
    return gql_class_factory(
        TemplateCollectionVariablesV1,
        {"static": '{"foo": "bar"}', "dynamic": [{"name": "foo", "query": "query {}"}]},
    )


def test_unpack_static_variables(
    collection_variables: TemplateCollectionVariablesV1,
) -> None:
    assert unpack_static_variables(collection_variables) == {"foo": "bar"}


def test_unpack_dynamic_variables_empty(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    mocker.patch("reconcile.templating.renderer.init_from_config")
    assert unpack_dynamic_variables(collection_variables) == {"foo": []}


def test_unpack_dynamic_variables(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.utils.gql.GqlApi", autospec=True)
    gql.query.return_value = {"foo": [{"bar": "baz"}]}
    mocker.patch("reconcile.templating.renderer.init_from_config", return_value=gql)
    assert unpack_dynamic_variables(collection_variables) == {"foo": [[{"bar": "baz"}]]}


def test_join_path() -> None:
    assert join_path("foo", "bar") == "foo/bar"
    assert join_path("foo", "/bar") == "foo/bar"


def test_local_file_persistence_write(tmp_path: Path) -> None:
    lfp = LocalFilePersistence(str(tmp_path))
    lfp.write("foo", "bar")
    assert (tmp_path / "foo").read_text() == "bar"


def test_local_file_persistence_read(tmp_path: Path) -> None:
    test_file = tmp_path / "foo"
    test_file.write_text("hello")
    lfp = LocalFilePersistence(str(tmp_path))
    assert lfp.read("foo") == "hello"
