import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import ANY, MagicMock, call

import pytest
from gitlab import GitlabGetError
from pytest_mock import MockerFixture
from ruamel import yaml

from reconcile.gql_definitions.templating.template_collection import (
    TemplateCollectionV1,
    TemplateCollectionVariablesQueriesV1,
    TemplateCollectionVariablesV1,
    TemplateV1,
)
from reconcile.templating.lib.merge_request_manager import MergeRequestManager, MrData
from reconcile.templating.lib.model import TemplateResult
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
from reconcile.utils.jinja2.utils import Jinja2TemplateError
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
def each() -> dict[str, Any]:
    return {"name": "item-0"}


@pytest.fixture
def collection_variables_foreach(
    gql_class_factory: Callable,
) -> TemplateCollectionVariablesV1:
    return gql_class_factory(
        TemplateCollectionVariablesV1,
        {
            "static": '{"foo": "{{ each.name }}"}',
            "dynamic": [{"name": "foo", "query": "query {{ each.name }}"}],
        },
    )


@pytest.fixture
def template_simple(gql_class_factory: Callable) -> TemplateV1:
    return gql_class_factory(
        TemplateV1,
        {
            "name": "test",
            "condition": "{{1 == 1}}",
            "targetPath": "/data/target_path",
            "template": "template",
        },
    )


@pytest.fixture
def template_overwrite(gql_class_factory: Callable) -> TemplateV1:
    return gql_class_factory(
        TemplateV1,
        {
            "name": "test",
            "condition": "{{1 == 1}}",
            "targetPath": "/data/target_path",
            "template": "template",
            "overwrite": True,
        },
    )


@pytest.fixture
def template_patch(gql_class_factory: Callable) -> TemplateV1:
    return gql_class_factory(
        TemplateV1,
        {
            "name": "test",
            "targetPath": "/data/target_path",
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
    return LocalFilePersistence(False, str(tmp_path))


@pytest.fixture
def ruaml_instance() -> yaml.YAML:
    return yaml.YAML()


@pytest.fixture
def template_renderer_integration(mocker: MockerFixture) -> TemplateRendererIntegration:
    return mocker.patch(
        "reconcile.templating.renderer.TemplateRendererIntegration", autospec=True
    )


@pytest.fixture
def template_result() -> TemplateResult:
    return TemplateResult(
        collection="test",
        enable_auto_approval=False,
    )


@pytest.fixture
def template_collection_variable(
    gql_class_factory: Callable,
) -> TemplateCollectionVariablesV1:
    return gql_class_factory(
        TemplateCollectionVariablesV1,
        {
            "static": '{"foo": "bar"}',
        },
    )


@pytest.fixture
def reconcile_mocks(mocker: MockerFixture) -> tuple:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    pt = mocker.patch.object(t, "process_template")
    mocker.patch("reconcile.templating.renderer.gql.get_api")
    p = mocker.MagicMock(LocalFilePersistence)
    p.dry_run = False
    r = create_ruamel_instance()

    return t, p, r, pt


@pytest.fixture
def vcs(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock(VCS)


@pytest.fixture
def mr_manager(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock(MergeRequestManager)


def test_unpack_static_variables(
    collection_variables: TemplateCollectionVariablesV1,
) -> None:
    assert unpack_static_variables(collection_variables, {}) == {"foo": "bar"}


def test_unpack_static_variables_foreach(
    collection_variables_foreach: TemplateCollectionVariablesV1,
    each: dict[str, Any],
) -> None:
    assert unpack_static_variables(collection_variables_foreach, each) == {
        "foo": "item-0"
    }


def test_unpack_static_variables_foreach_error(
    collection_variables_foreach: TemplateCollectionVariablesV1,
) -> None:
    with pytest.raises(Jinja2TemplateError):
        unpack_static_variables(collection_variables_foreach, {})


def test_unpack_dynamic_variables_empty(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    gql.query.return_value = {}
    assert unpack_dynamic_variables(collection_variables, {}, gql) == {"foo": {}}


def test_unpack_dynamic_variables(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    gql.query.return_value = {"foo": [{"bar": "baz"}]}
    assert unpack_dynamic_variables(collection_variables, {}, gql) == {
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
    assert unpack_dynamic_variables(collection_variables, {}, gql) == {
        "foo": {"baz": [{"baz": "zab"}], "foo": [{"bar": "baz"}, {"faa": "baz"}]}
    }


def test_unpack_dynamic_variables_templated_query(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    collection_variables.dynamic = [
        TemplateCollectionVariablesQueriesV1(
            name="baz", query="templated query {{ static.foo }}"
        )
    ]
    unpack_dynamic_variables(collection_variables, {}, gql)
    gql.query.assert_called_once_with("templated query bar")


def test_unpack_dynamic_variables_templated_query_jinja_error(
    mocker: MockerFixture, collection_variables: TemplateCollectionVariablesV1
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    collection_variables.dynamic = [
        TemplateCollectionVariablesQueriesV1(
            name="foo", query="templated query {{ static.does_not_exist }}"
        )
    ]
    with pytest.raises(Jinja2TemplateError):
        unpack_dynamic_variables(collection_variables, {}, gql)


def test_unpack_dynamic_variables_foreach(
    mocker: MockerFixture,
    collection_variables_foreach: TemplateCollectionVariablesV1,
    each: dict[str, Any],
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    unpack_dynamic_variables(collection_variables_foreach, each, gql)
    gql.query.assert_called_once_with("query item-0")


def test_unpack_dynamic_variables_foreach_error(
    mocker: MockerFixture,
    collection_variables_foreach: TemplateCollectionVariablesV1,
) -> None:
    gql = mocker.patch("reconcile.templating.renderer.gql.GqlApi", autospec=True)
    with pytest.raises(Jinja2TemplateError):
        unpack_dynamic_variables(collection_variables_foreach, {}, gql)


def test_join_path() -> None:
    assert join_path("foo", "bar") == "foo/bar"
    assert join_path("foo", "/bar") == "foo/bar"


def test_local_file_persistence_write(tmp_path: Path) -> None:
    with LocalFilePersistence(
        dry_run=False, app_interface_data_path=str(tmp_path)
    ) as lfp:
        lfp.write(TemplateOutput(path="/data/foo", content="bar"))
    assert (tmp_path / "data" / "foo").read_text() == "bar"


def test_local_file_persistence_write_dry_run(tmp_path: Path) -> None:
    with LocalFilePersistence(
        dry_run=True, app_interface_data_path=str(tmp_path)
    ) as lfp:
        lfp.write(TemplateOutput(path="/data/foo", content="bar"))
    assert not (tmp_path / "data" / "foo").exists()


def test_local_file_persistence_read(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    os.makedirs(data_dir)
    test_file = data_dir / "foo"
    test_file.write_text("hello")
    lfp = LocalFilePersistence(dry_run=False, app_interface_data_path=str(tmp_path))
    assert lfp.read("data/foo") == "hello"


def test_crg_file_persistence_write(
    vcs: MagicMock,
    mr_manager: MagicMock,
    tmp_path: Path,
    template_result: TemplateResult,
) -> None:
    with ClonedRepoGitlabPersistence(
        dry_run=False, local_path=str(tmp_path), vcs=vcs, mr_manager=mr_manager
    ) as crg:
        crg.result = template_result
        crg.write(TemplateOutput(path="/data/foo", content="bar"))

    mr_manager.housekeeping.assert_called_once()
    mr_manager.create_merge_request.assert_called_once_with(
        MrData(result=template_result, auto_approved=False)
    )


def test_crg_file_persistence_write_dry_run(
    vcs: MagicMock,
    mr_manager: MagicMock,
    tmp_path: Path,
    template_result: TemplateResult,
) -> None:
    with ClonedRepoGitlabPersistence(
        dry_run=True, local_path=str(tmp_path), vcs=vcs, mr_manager=mr_manager
    ) as crg:
        crg.result = template_result
        crg.write(TemplateOutput(path="/data/foo", content="bar"))

    mr_manager.housekeeping.assert_not_called()
    mr_manager.create_merge_request.assert_not_called()


def test_crg_file_persistence_write_no_auto_approval(
    vcs: MagicMock,
    mr_manager: MagicMock,
    tmp_path: Path,
    template_result: TemplateResult,
) -> None:
    template_result.enable_auto_approval = False
    with ClonedRepoGitlabPersistence(
        dry_run=False, local_path=str(tmp_path), vcs=vcs, mr_manager=mr_manager
    ) as crg:
        crg.result = template_result
        tauto = TemplateOutput(path="/data/foo", content="bar", auto_approved=True)
        crg.write(tauto)
        tnoauto = TemplateOutput(path="/data/foo2", content="bar2", auto_approved=False)
        crg.write(tnoauto)

    assert crg.result.outputs == [tauto, tnoauto]
    mr_manager.create_merge_request.assert_called_with(
        MrData(result=template_result, auto_approved=False)
    )


def test_crg_file_persistence_write_auto_approval(
    tmp_path: Path,
    template_result: TemplateResult,
    vcs: MagicMock,
    mr_manager: MagicMock,
) -> None:
    template_result.enable_auto_approval = True
    with ClonedRepoGitlabPersistence(
        dry_run=False, local_path=str(tmp_path), vcs=vcs, mr_manager=mr_manager
    ) as crg:
        crg.result = template_result
        tauto = TemplateOutput(path="/data/foo", content="bar", auto_approved=True)
        crg.write(tauto)
        tnoauto = TemplateOutput(path="/data/foo2", content="bar2", auto_approved=False)
        crg.write(tnoauto)

    assert mr_manager.create_merge_request.call_count == 2
    mr_manager.create_merge_request.assert_has_calls([
        call(
            MrData(
                result=TemplateResult(
                    collection=f"{template_result.collection}-auto-approved",
                    enable_auto_approval=True,
                    labels=template_result.labels,
                    outputs=[tauto],
                ),
                auto_approved=True,
            )
        ),
        call(
            MrData(
                result=TemplateResult(
                    collection=f"{template_result.collection}-not-auto-approved",
                    enable_auto_approval=True,
                    labels=template_result.labels,
                    outputs=[tnoauto],
                ),
                auto_approved=False,
            )
        ),
    ])


def test_crg_file_persistence_read_found(
    vcs: MagicMock, mr_manager: MagicMock, tmp_path: Path
) -> None:
    os.makedirs(tmp_path / "data")
    test_file = tmp_path / "data" / "foo"
    test_file.write_text("hello")
    crg = ClonedRepoGitlabPersistence(False, str(tmp_path), vcs, mr_manager)
    assert crg.read("data/foo") == "hello"


def test_crg_file_persistence_read_miss(
    vcs: MagicMock, mr_manager: MagicMock, tmp_path: Path
) -> None:
    vcs.get_file_content_from_app_interface_ref.side_effect = GitlabGetError()
    crg = ClonedRepoGitlabPersistence(False, str(tmp_path), vcs, mr_manager)
    assert crg.read("data/foo") is None


def test_persistence_transaction_dry_run(mocker: MockerFixture) -> None:
    persistence_mock = mocker.MagicMock(LocalFilePersistence)
    output = TemplateOutput(path="foo", content="updated_value")
    output2 = TemplateOutput(path="foo2", content="updated_value")

    persistence_mock.dry_run = True
    with PersistenceTransaction(persistence_mock) as p:
        p.write(output)
    persistence_mock.write.assert_not_called()

    persistence_mock.dry_run = False
    print(persistence_mock.dry_run)
    with PersistenceTransaction(persistence_mock) as p:
        p.write(output)
        p.write(output2)
    assert persistence_mock.write.call_count == 2
    persistence_mock.write.assert_has_calls([mocker.call(output), mocker.call(output2)])


def test_persistence_transaction_read(mocker: MockerFixture) -> None:
    persistence_mock = mocker.MagicMock(LocalFilePersistence)
    persistence_mock.read.return_value = "foo"
    persistence_mock.dry_run = False
    p = PersistenceTransaction(persistence_mock)
    p.read("foo")
    p.read("foo")

    persistence_mock.read.assert_called_once_with("foo")
    assert p.content_cache == {"foo": "foo"}


def test_persistence_transaction_write(
    mocker: MockerFixture,
) -> None:
    test_path = "foo"
    persistence_mock = mocker.MagicMock(LocalFilePersistence)
    persistence_mock.read.return_value = "initial_value"
    persistence_mock.dry_run = False
    p = PersistenceTransaction(persistence_mock)
    p.read(test_path)
    assert p.content_cache == {test_path: "initial_value"}

    output = TemplateOutput(path=test_path, content="updated_value")
    p.write(output)

    assert p.output_cache == {output.path: output}
    assert p.content_cache == {test_path: "updated_value"}

    persistence_mock.write.assert_not_called()


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
    assert output.path == "/data/target_path"
    assert output.content == "template"


def test_process_template_skip(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
) -> None:
    local_file_persistence.write(
        TemplateOutput(path="/data/target_path", content="bar")
    )
    local_file_persistence.flush()
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance
    )
    assert output is None


def test_process_template_overwrite(
    template_overwrite: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
) -> None:
    local_file_persistence.write(
        TemplateOutput(path="/data/target_path", content="bar")
    )
    local_file_persistence.flush()
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    output = t.process_template(
        template_overwrite, {}, local_file_persistence, ruaml_instance
    )
    assert output
    assert output.path == "/data/target_path"
    assert output.content == "template"


def test_process_template_patch_fail(
    template_patch: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader
    with pytest.raises(ValueError, match="Can not patch non-existing file"):
        t.process_template(template_patch, {}, local_file_persistence, ruaml_instance)


def test_process_template_wrong_condition(
    template_simple: TemplateV1,
    local_file_persistence: LocalFilePersistence,
    ruaml_instance: yaml.YAML,
    secret_reader: SecretReader,
) -> None:
    t = TemplateRendererIntegration(TemplateRendererIntegrationParams())
    t._secret_reader = secret_reader

    template_simple.condition = "{{ false }}"
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance
    )
    assert output is None

    template_simple.condition = "{{ true }}"
    output = t.process_template(
        template_simple, {}, local_file_persistence, ruaml_instance
    )
    # just assert some output is comming back, content does not matter for this case
    assert output is not None


def test_reconcile_simple(
    mocker: MockerFixture,
    reconcile_mocks: tuple,
    template_collection: TemplateCollectionV1,
) -> None:
    gtc = mocker.patch("reconcile.templating.renderer.get_template_collections")
    gtc.return_value = [template_collection]

    t, p, r, pt = reconcile_mocks
    t.reconcile(p, r)

    pt.assert_called_once()
    assert pt.call_args[0] == (
        TemplateV1(
            name="test",
            condition="{{1 == 1}}",
            targetPath="/data/target_path",
            patch=None,
            template="template",
            autoApproved=None,
            templateRenderOptions=None,
            overwrite=None,
        ),
        {},
        ANY,
        r,
    )


def test_reconcile_twice(
    mocker: MockerFixture,
    reconcile_mocks: tuple,
    template_collection: TemplateCollectionV1,
) -> None:
    t, p, r, pt = reconcile_mocks

    gtc = mocker.patch("reconcile.templating.renderer.get_template_collections")
    gtc.return_value = [template_collection, template_collection]

    t.reconcile(p, r)

    assert pt.call_count == 2


def test_reconcile_variables(
    mocker: MockerFixture,
    reconcile_mocks: tuple,
    template_collection: TemplateCollectionV1,
    template_collection_variable: TemplateCollectionVariablesV1,
) -> None:
    t, p, r, pt = reconcile_mocks

    gtc = mocker.patch("reconcile.templating.renderer.get_template_collections")
    template_collection.variables = template_collection_variable

    gtc.return_value = [template_collection]
    # not really using template_collection_variable fixture content, since we mock the return value
    udv = mocker.patch("reconcile.templating.renderer.unpack_dynamic_variables")
    udv.return_value = {"foo": "bar"}
    usv = mocker.patch("reconcile.templating.renderer.unpack_static_variables")
    usv.return_value = {"baz": "qux"}

    t.reconcile(p, r)

    pt.assert_called_once()
    assert pt.call_args[0] == (
        ANY,
        {"dynamic": {"foo": "bar"}, "static": {"baz": "qux"}},
        ANY,
        r,
    )


def test__calc_result_hash(template_result: TemplateResult) -> None:
    template_result.outputs = [TemplateOutput(path="/data/target_path", content="bar")]
    assert (
        template_result.calc_result_hash()
        == "168166ae4cc901088f1e6b714592c48bcbccfecdff6419b074718cba32d83253"
    )
    template_result.outputs = [TemplateOutput(path="/data/target_path", content="foo")]
    assert (
        template_result.calc_result_hash()
        == "eb831a9330b7a33f4a5981dc67b67b88a798399c99f14a4d0bd06bd56a84f845"
    )
