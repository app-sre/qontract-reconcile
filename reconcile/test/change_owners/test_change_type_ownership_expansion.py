import pytest

from reconcile.change_owners.bundle import BundleFileType
from reconcile.change_owners.change_types import (
    ChangeTypeCycleError,
    ChangeTypePriority,
    init_change_type_processors,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import (
    MockFileDiffResolver,
    build_change_type_change,
    build_jsonpath_change,
    build_test_datafile,
)


@pytest.fixture
def namespace_change_type() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="namespace",
        description="namespace",
        contextType=BundleFileType.DATAFILE.value,
        contextSchema="namespace-1.yml",
        disabled=False,
        priority=ChangeTypePriority.HIGH.value,
        changes=[
            build_jsonpath_change(
                schema="namespace-1.yml",
                selectors=["description"],
            )
        ],
        inherit=None,
        implicitOwnership=[],
    )


@pytest.fixture
def app_change_type() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="app",
        description="app",
        contextType=BundleFileType.DATAFILE.value,
        contextSchema="app-1.yml",
        disabled=False,
        priority=ChangeTypePriority.HIGH.value,
        changes=[
            build_change_type_change(
                schema="app-1.yml",
                change_type_names=["namespace"],
                context_selector="app",
                context_when=None,
            )
        ],
        inherit=None,
        implicitOwnership=[],
    )


def test_change_type_ownership_resolve(
    namespace_change_type: ChangeTypeV1, app_change_type: ChangeTypeV1
):
    namespace_change = build_test_datafile(
        filepath="my-namespace.yml",
        schema=namespace_change_type.context_schema,
        content={"app": "my-app.yml", "description": "my-description"},
    ).create_bundle_change(jsonpath_patches={"$.description": "updated-description"})

    processors = init_change_type_processors(
        [namespace_change_type, app_change_type],
        MockFileDiffResolver(fail_on_unknown_path=False),
    )

    namespace_change_type_processor = processors[namespace_change_type.name]
    contexts = namespace_change_type_processor.find_context_file_refs(
        namespace_change.fileref, namespace_change.old, namespace_change.new
    )
    ownership_dict = {ro.owned_file_ref.path: ro for ro in contexts}
    assert len(ownership_dict) == 2

    # verify that the regular context for the changed file is present
    assert "my-namespace.yml" in ownership_dict
    assert ownership_dict["my-namespace.yml"].change_type.name == "namespace"

    # then verify that a context for the app of the namespace has been derived
    # from the ownership expansion
    assert "my-app.yml" in ownership_dict
    assert ownership_dict["my-app.yml"].change_type.name == "app"


def test_change_type_expansion_cycle(
    namespace_change_type: ChangeTypeV1, app_change_type: ChangeTypeV1
):
    namespace_change_type.changes = app_change_type.changes
    namespace_change_type.changes[0].change_types[0].name = "app"  # type: ignore

    with pytest.raises(ChangeTypeCycleError):
        init_change_type_processors(
            [namespace_change_type, app_change_type],
            MockFileDiffResolver(fail_on_unknown_path=False),
        )
