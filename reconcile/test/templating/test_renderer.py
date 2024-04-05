from datetime import datetime
from pathlib import Path
from typing import Callable

import pytest
from gitlab import GitlabGetError
from pytest_mock import MockerFixture
from ruamel import yaml

from reconcile.gql_definitions.templating.template_collection import (
    TemplateCollectionV1,
    TemplateCollectionVariablesV1,
    TemplateV1,
)
from reconcile.templating.lib.merge_request_manager import MergeRequestManager
from reconcile.templating.renderer import (
    GitlabFilePersistence,
    LocalFilePersistence,
    PersistenceContext,
    TemplateOutput,
    TemplateRendererIntegration,
    TemplateRendererIntegrationParams,
    join_path,
    unpack_dynamic_variables,
    unpack_static_variables,
)
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State
from reconcile.utils.vcs import VCS


@pytest.fixture
def collection_variables(gql_class_factory: Callable) -> TemplateCollectionVariablesV1:
    return gql_class_factory(
        TemplateCollectionVariablesV1,
        {"static": '{"foo": "bar"}', "dynamic": [{"name": "foo", "query": "query {}"}]},
    )


@pytest.fixture
def template_simple(gql_class_factory: Callable) -> TemplateV1:
    return gql_class_factory(
        TemplateV1,
        {
            "name": "test",
            "condition": "{{1 == 1}}",
            "targetPath": "/target_path",
            "template": "template",
        },
    )


@pytest.fixture
def template_collection(
    gql_class_factory: Callable, template_simple: TemplateV1
) -> TemplateCollectionV1:
    return gql_class_factory(
        TemplateCollectionV1,
        {
            "name": "test",
            "variables": None,
            "templates": [template_simple.dict(by_alias=True)],
        },
    )


@pytest.fixture
def local_file_persistence(tmp_path: Path) -> LocalFilePersistence:
    return LocalFilePersistence(str(tmp_path))


@pytest.fixture
def ruaml_instance() -> yaml.YAML:
    return yaml.YAML()


@pytest.fixture
def template_renderer_integration(mocker: MockerFixture) -> TemplateRendererIntegration:
    return mocker.patch(
        "reconcile.templating.renderer.TemplateRendererIntegration", autospec=True
    )


def test_unpack_static_variables(
    collection_variables: TemplateCollectionVariablesV1,
) -> None:
    assert unpack_static_variables(collection_variables) == {"foo": "bar"}


def test_unpack_dynamic_variables_empty(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    gql.query.return_value = {}
    assert unpack_dynamic_variables(collection_variables, gql) == {"foo": {}}


def test_unpack_dynamic_variables(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    gql.query.return_value = {"foo": [{"bar": "baz"}]}
    assert unpack_dynamic_variables(collection_variables, gql) == {
        "foo": {"foo": [{"bar": "baz"}]}
    }


def test_unpack_dynamic_variables_multiple_result(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    gql.query.return_value = {
        "baz": [{"baz": "zab"}],
        "foo": [{"bar": "baz"}, {"faa": "baz"}],
    }
    assert unpack_dynamic_variables(collection_variables, gql) == {
        "foo": {"baz": [{"baz": "zab"}], "foo": [{"bar": "baz"}, {"faa": "baz"}]}
    }


def test_join_path() -> None:
    assert join_path("foo", "bar") == "foo/bar"
    assert join_path("foo", "/bar") == "foo/bar"


def test_local_file_persistence_write(tmp_path: Path) -> None:
    lfp = LocalFilePersistence(str(tmp_path))
    lfp.write([TemplateOutput(path="/foo", content="bar")])
    assert (tmp_path / "foo").read_text() == "bar"


def test_local_file_persistence_read(tmp_path: Path) -> None:
    test_file = tmp_path / "foo"
    test_file.write_text("hello")
    lfp = LocalFilePersistence(str(tmp_path))
    assert lfp.read("foo") == "hello"


def test_gitlab_file_persistence_write(mocker: MockerFixture) -> None:
    vcs = mocker.MagicMock(VCS)
    mr_manager = mocker.MagicMock(MergeRequestManager)
    output = [TemplateOutput(path="/foo", content="bar")]
    gfp = GitlabFilePersistence(vcs, mr_manager)
    gfp.write(output)

    mr_manager.housekeeping.assert_called_once()
    mr_manager.create_merge_request.assert_called_once_with(output)


def test_gitlable_file_persistence_read_found(mocker: MockerFixture) -> None:
    vcs = mocker.MagicMock(VCS)
    vcs.get_file_content_from_app_interface_master.return_value = "hello"
    mr_manager = mocker.MagicMock(MergeRequestManager)
    gfp = GitlabFilePersistence(vcs, mr_manager)

    assert gfp.read("foo") == "hello"
    vcs.get_file_content_from_app_interface_master.assert_called_once_with("foo")


def test_gitlable_file_persistence_read_miss(mocker: MockerFixture) -> None:
    vcs = mocker.MagicMock(VCS)
    vcs.get_file_content_from_app_interface_master.side_effect = GitlabGetError()
    mr_manager = mocker.MagicMock(MergeRequestManager)
    gfp = GitlabFilePersistence(vcs, mr_manager)

    assert gfp.read("foo") is None
    vcs.get_file_content_from_app_interface_master.assert_called_once_with("foo")


def test_process_template_simple(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance
    )
    assert output
    assert output.path == "/target_path"
    assert output.content == "template"


def test_process_template_overwrite(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
) -> None:
    local_file_persistence.write([TemplateOutput(path="/target_path", content="bar")])
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance
    )
    assert output
    assert output.path == "/target_path"
    assert output.content == "template"


def test_process_template_match(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
) -> None:
    local_file_persistence.write([
        TemplateOutput(path="/target_path", content="template")
    ])
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance
    )
    assert output is None


def test_reconcile_state_mismatch(
    mocker: MockerFixture, template_collection: TemplateCollectionV1
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    state = mocker.MagicMock(State)
    state.exists.return_value = True
    pt = mocker.patch.object(t, "process_template")
    mocker.patch("reconcile.templating.renderer.init_from_config")
    gtc = mocker.patch("reconcile.templating.renderer.get_template_collections")
    gtc.return_value = [template_collection]
    p = mocker.MagicMock(LocalFilePersistence)
    t.reconcile(
        False,
        p,
        create_ruamel_instance(),
        state,
    )

    pt.assert_called_once()
    state.add.assert_called_once()
    p.write.assert_called_once()


def test_reconcile_state_match(
    mocker: MockerFixture, template_collection: TemplateCollectionV1
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    state = mocker.MagicMock(State)
    state.exists.return_value = True
    # Hash optained using debugger
    state.get.return_value = {
        "hash": "f8e46492df18572b06967588c8074ef5a4a7ba2810d5f901ea94098f80856568",
        "timestamp": datetime.now().isoformat(),
    }
    pt = mocker.patch.object(t, "process_template")
    mocker.patch("reconcile.templating.renderer.init_from_config")
    gtc = mocker.patch("reconcile.templating.renderer.get_template_collections")
    gtc.return_value = [template_collection]
    p = mocker.MagicMock(LocalFilePersistence)

    t.reconcile(
        False,
        p,
        create_ruamel_instance(),
        state,
    )

    pt.assert_not_called()
    p.write.assert_not_called()


def test_persistence_context_dry_run(mocker: MockerFixture) -> None:
    persistence_mock = mocker.MagicMock(LocalFilePersistence)

    with PersistenceContext(persistence_mock, True):
        pass
    persistence_mock.write.assert_not_called()

    with PersistenceContext(persistence_mock, False):
        pass
    persistence_mock.write.assert_called_once()


def test_persistence_read(mocker: MockerFixture) -> None:
    persistence_mock = mocker.MagicMock(LocalFilePersistence)
    persistence_mock.read.return_value = "foo"
    p = PersistenceContext(persistence_mock, False)
    p.read("foo")
    p.read("foo")

    persistence_mock.read.assert_called_once_with("foo")
    assert p.content_cache == {"foo": "foo"}


def test_persistence_write(mocker: MockerFixture) -> None:
    test_path = "foo"
    persistence_mock = mocker.MagicMock(LocalFilePersistence)
    persistence_mock.read.return_value = "initial_value"
    p = PersistenceContext(persistence_mock, False)
    p.read(test_path)
    assert p.content_cache == {test_path: "initial_value"}

    output = TemplateOutput(path=test_path, content="updated_value")
    p.write([])
    p.write([output])

    assert p.output_cache == {output.path: output}
    assert p.content_cache == {test_path: "updated_value"}

    persistence_mock.write.assert_not_called()
