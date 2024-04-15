import os
from pathlib import Path
from typing import Callable
from unittest.mock import ANY

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
from reconcile.templating.lib.model import TemplateInput
from reconcile.templating.renderer import (
    ClonedRepoGitlabPersistence,
    LocalFilePersistence,
    PersistenceTransaction,
    TemplateOutput,
    TemplateRendererIntegration,
    TemplateRendererIntegrationParams,
    join_path,
    unpack_dynamic_variables,
    unpack_static_variables,
)
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.secret_reader import SecretReader
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
def template_patch(gql_class_factory: Callable) -> TemplateV1:
    return gql_class_factory(
        TemplateV1,
        {
            "name": "test",
            "targetPath": "/target_path",
            "template": "template",
            "patch": {"path": "$.patch_path", "identifier": "identifier"},
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
    os.mkdir(tmp_path / "data")
    return LocalFilePersistence(str(tmp_path / "data"))


@pytest.fixture
def ruaml_instance() -> yaml.YAML:
    return yaml.YAML()


@pytest.fixture
def template_renderer_integration(mocker: MockerFixture) -> TemplateRendererIntegration:
    return mocker.patch(
        "reconcile.templating.renderer.TemplateRendererIntegration", autospec=True
    )


@pytest.fixture
def template_input() -> TemplateInput:
    return TemplateInput(
        collection="test",
        collection_hash="test",
        enable_auto_approval=False,
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


def test_local_file_persistence_write(
    tmp_path: Path, template_input: TemplateInput
) -> None:
    os.makedirs(tmp_path / "data")
    lfp = LocalFilePersistence(str(tmp_path / "data"))
    lfp.write([TemplateOutput(path="/foo", content="bar", input=template_input)])
    assert (tmp_path / "data" / "foo").read_text() == "bar"


def test_local_file_persistence_read(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    os.makedirs(data_dir)
    test_file = data_dir / "foo"
    test_file.write_text("hello")
    lfp = LocalFilePersistence(str(data_dir))
    assert lfp.read("foo") == "hello"


def test_crg_file_persistence_write(
    mocker: MockerFixture, tmp_path: Path, template_input: TemplateInput
) -> None:
    vcs = mocker.MagicMock(VCS)
    mr_manager = mocker.MagicMock(MergeRequestManager)
    output = [TemplateOutput(path="/foo", content="bar", input=template_input)]
    crg = ClonedRepoGitlabPersistence(str(tmp_path), vcs, mr_manager)
    crg.write(output)

    mr_manager.housekeeping.assert_called_once()
    mr_manager.create_merge_request.assert_called_once_with(output)


def test_crg_file_persistence_write_auto_approval(
    mocker: MockerFixture, tmp_path: Path, template_input: TemplateInput
) -> None:
    vcs = mocker.MagicMock(VCS)
    mr_manager = mocker.MagicMock(MergeRequestManager)
    crg = ClonedRepoGitlabPersistence(str(tmp_path), vcs, mr_manager)

    tauto = TemplateOutput(
        path="/foo", content="bar", auto_approved=True, input=template_input
    )
    tnoauto = TemplateOutput(
        path="/foo2", content="bar2", auto_approved=False, input=template_input
    )
    output = [tauto, tnoauto]
    crg.write(output)

    mr_manager.create_merge_request.assert_called_with(output)

    template_input.enable_auto_approval = True
    output = [tauto, tnoauto]

    crg.write(output)

    mr_manager.create_merge_request.assert_called_with([tauto])


def test_crg_file_persistence_read_found(mocker: MockerFixture, tmp_path: Path) -> None:
    vcs = mocker.MagicMock(VCS)
    os.makedirs(tmp_path / "data")
    test_file = tmp_path / "data" / "foo"
    test_file.write_text("hello")
    mr_manager = mocker.MagicMock(MergeRequestManager)
    crg = ClonedRepoGitlabPersistence(str(tmp_path), vcs, mr_manager)

    assert crg.read("foo") == "hello"


def test_crg_file_persistence_read_miss(mocker: MockerFixture, tmp_path: Path) -> None:
    vcs = mocker.MagicMock(VCS)
    vcs.get_file_content_from_app_interface_master.side_effect = GitlabGetError()
    mr_manager = mocker.MagicMock(MergeRequestManager)
    crg = ClonedRepoGitlabPersistence(str(tmp_path), vcs, mr_manager)

    assert crg.read("foo") is None


def test_persistence_transaction_dry_run(
    mocker: MockerFixture, template_input: TemplateInput
) -> None:
    test_path = "foo"
    persistence_mock = mocker.MagicMock(LocalFilePersistence)

    output = TemplateOutput(
        path=test_path, content="updated_value", input=template_input
    )

    with PersistenceTransaction(persistence_mock, True) as p:
        p.write([])
        p.write([output])
    persistence_mock.write.assert_not_called()

    with PersistenceTransaction(persistence_mock, False) as p:
        p.write([])
        p.write([output])
    persistence_mock.write.assert_called_once()


def test_persistence_transaction_read(mocker: MockerFixture) -> None:
    persistence_mock = mocker.MagicMock(LocalFilePersistence)
    persistence_mock.read.return_value = "foo"
    p = PersistenceTransaction(persistence_mock, False)
    p.read("foo")
    p.read("foo")

    persistence_mock.read.assert_called_once_with("foo")
    assert p.content_cache == {"foo": "foo"}


def test_persistence_transaction_write(
    mocker: MockerFixture, template_input: TemplateInput
) -> None:
    test_path = "foo"
    persistence_mock = mocker.MagicMock(LocalFilePersistence)
    persistence_mock.read.return_value = "initial_value"
    p = PersistenceTransaction(persistence_mock, False)
    p.read(test_path)
    assert p.content_cache == {test_path: "initial_value"}

    output = TemplateOutput(
        path=test_path, content="updated_value", input=template_input
    )
    p.write([])
    p.write([output])

    assert p.output_cache == {output.path: output}
    assert p.content_cache == {test_path: "updated_value"}

    persistence_mock.write.assert_not_called()


def test_process_template_simple(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
    template_input: TemplateInput,
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance, template_input
    )
    assert output
    assert output.path == "/target_path"
    assert output.content == "template"


def test_process_template_overwrite(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
    template_input: TemplateInput,
) -> None:
    local_file_persistence.write([
        TemplateOutput(path="/target_path", content="bar", input=template_input)
    ])
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance, template_input
    )
    assert output
    assert output.path == "/target_path"
    assert output.content == "template"


def test_process_template_patch_fail(
    template_patch: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
    template_input: TemplateInput,
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    with pytest.raises(ValueError, match="Can not patch non-existing file"):
        t.process_template(
            template_patch, {}, local_file_persistence, ruaml_instance, template_input
        )


def test_process_template_wrong_condition(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
    template_input: TemplateInput,
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader

    template_simple.condition = "{{ false }}"
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance, template_input
    )
    assert output is None

    template_simple.condition = "{{ true }}"
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance, template_input
    )
    # just assert some output is comming back, content does not matter for this case
    assert output is not None


def test_reconcile(
    mocker: MockerFixture, template_collection: TemplateCollectionV1
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    pt = mocker.patch.object(t, "process_template")
    mocker.patch("reconcile.templating.renderer.init_from_config")
    gtc = mocker.patch("reconcile.templating.renderer.get_template_collections")
    gtc.return_value = [template_collection]
    p = mocker.MagicMock(LocalFilePersistence)
    r = create_ruamel_instance()
    t.reconcile(
        False,
        p,
        r,
    )

    pt.assert_called_once()
    assert pt.call_args[0] == (
        TemplateV1(
            name="test",
            condition="{{1 == 1}}",
            targetPath="/target_path",
            patch=None,
            template="template",
            autoApproved=None,
        ),
        {},
        ANY,
        r,
        ANY,
    )
    p.write.assert_called_once()
