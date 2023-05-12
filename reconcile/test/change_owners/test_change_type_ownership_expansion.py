import pytest

from reconcile.change_owners.bundle import BundleFileType
from reconcile.change_owners.change_types import (
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
def app_hierarchy_change_type() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="app-hierarchy",
        description="app-hierarchy",
        contextType=BundleFileType.DATAFILE.value,
        contextSchema="app-1.yml",
        disabled=False,
        priority=ChangeTypePriority.HIGH.value,
        changes=[
            build_change_type_change(
                schema="app-1.yml",
                change_type_names=["app-hierarchy"],
                context_selector="parent",
                context_when=None,
            ),
        ],
        inherit=None,
        implicitOwnership=[],
    )


@pytest.fixture
def saas_file_change_type() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="saas-files-of-namespaces",
        description="namespace",
        contextType=BundleFileType.DATAFILE.value,
        contextSchema="namespace-1.yml",
        disabled=False,
        priority=ChangeTypePriority.HIGH.value,
        changes=[
            build_jsonpath_change(
                schema="saas-file-1.yml",
                selectors=["description"],
                context_selector="namespace",
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
            ),
            build_change_type_change(
                schema="app-1.yml",
                change_type_names=["saas-files-of-namespaces"],
                context_selector="app",
                context_when=None,
            ),
        ],
        inherit=None,
        implicitOwnership=[],
    )


def test_change_type_ownership_resolve(
    namespace_change_type: ChangeTypeV1,
    app_change_type: ChangeTypeV1,
    saas_file_change_type: ChangeTypeV1,
) -> None:
    namespace_change = build_test_datafile(
        filepath="my-namespace.yml",
        schema=namespace_change_type.context_schema,
        content={"app": "my-app.yml", "description": "my-description"},
    ).create_bundle_change(jsonpath_patches={"$.description": "updated-description"})

    processors = init_change_type_processors(
        [namespace_change_type, app_change_type, saas_file_change_type],
        MockFileDiffResolver(fail_on_unknown_path=False),
    )

    namespace_change_type_processor = processors[namespace_change_type.name]
    contexts = namespace_change_type_processor.find_context_file_refs(
        namespace_change.fileref, namespace_change.old, namespace_change.new, set()
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


def test_change_type_ownership_expansion_with_context_selector(
    namespace_change_type: ChangeTypeV1,
    app_change_type: ChangeTypeV1,
    saas_file_change_type: ChangeTypeV1,
) -> None:
    """
    test the interaction of a context lookup in one change-type that is used
    for ownership expansion.

    the saas_file_change_type reacts to a change to a saas-file and maps it to
    it's namespace. then the ownership expansion kicks in and dervies ownership
    from the namespace to the app.
    """
    saas_file_change = build_test_datafile(
        filepath="my-saas-file.yml",
        schema="saas-file-1.yml",
        content={"namespace": "my-namespace.yml", "description": "my-description"},
    ).create_bundle_change(jsonpath_patches={"$.description": "updated-description"})

    processors = init_change_type_processors(
        [namespace_change_type, app_change_type, saas_file_change_type],
        MockFileDiffResolver()
        .register_raw_diff(
            path="my-namespace.yml",
            old={"app": "my-app.yml", "description": "my-description"},
            new={"app": "my-app.yml", "description": "my-description"},
        )
        .register_raw_diff(
            path="my-app.yml",
            old={"name": "my-app"},
            new={"name": "my-app"},
        ),
    )

    saas_file_change_type_processor = processors[saas_file_change_type.name]
    contexts = saas_file_change_type_processor.find_context_file_refs(
        saas_file_change.fileref, saas_file_change.old, saas_file_change.new, set()
    )
    ownership_dict = {ro.owned_file_ref.path: ro for ro in contexts}
    assert len(ownership_dict) == 2

    # verify that the regular context has been derived from the saas file
    # change to the namespace
    assert "my-namespace.yml" in ownership_dict
    assert (
        ownership_dict["my-namespace.yml"].change_type.name
        == "saas-files-of-namespaces"
    )

    # then verify that a context for the app of the namespace has been derived
    # from the ownership expansion
    assert "my-app.yml" in ownership_dict
    assert ownership_dict["my-app.yml"].change_type.name == "app"


def test_change_type_expansion_hierarchy(
    app_hierarchy_change_type: ChangeTypeV1,
) -> None:
    app_change = build_test_datafile(
        filepath="app.yml",
        schema="app-1.yml",
        content={
            "name": "app",
            "parent": "parent-app.yml",
            "description": "my-description",
        },
    ).create_bundle_change(jsonpath_patches={"$.description": "updated-description"})

    processors = init_change_type_processors(
        [app_hierarchy_change_type],
        MockFileDiffResolver()
        .register_raw_diff(
            path="parent-app.yml",
            old={"name": "parent-app", "parent": "grand-parent-app.yml"},
            new={"name": "parent-app", "parent": "grand-parent-app.yml"},
        )
        .register_raw_diff(
            path="grand-parent-app.yml",
            old={"name": "grant-parent-app"},
            new={"name": "grant-parent-app"},
        ),
    )

    app_hierarchy_change_type_processor = processors[app_hierarchy_change_type.name]
    contexts = app_hierarchy_change_type_processor.find_context_file_refs(
        app_change.fileref, app_change.old, app_change.new, set()
    )
    ownership_dict = {ro.owned_file_ref.path: ro for ro in contexts}
    assert len(ownership_dict) == 3

    assert "app.yml" in ownership_dict
    assert ownership_dict["app.yml"].change_type.name == app_hierarchy_change_type.name

    assert "parent-app.yml" in ownership_dict
    assert (
        ownership_dict["parent-app.yml"].change_type.name
        == app_hierarchy_change_type.name
    )

    assert "grand-parent-app.yml" in ownership_dict
    assert (
        ownership_dict["grand-parent-app.yml"].change_type.name
        == app_hierarchy_change_type.name
    )


def test_change_type_expansion_hierarchy_cycle_prevention(
    app_hierarchy_change_type: ChangeTypeV1,
) -> None:
    app_change = build_test_datafile(
        filepath="app.yml",
        schema="app-1.yml",
        content={
            "name": "app",
            "parent": "parent-app.yml",
            "description": "my-description",
        },
    ).create_bundle_change(jsonpath_patches={"$.description": "updated-description"})

    processors = init_change_type_processors(
        [app_hierarchy_change_type],
        MockFileDiffResolver()
        .register_bundle_change(app_change)
        .register_raw_diff(
            path="parent-app.yml",
            old={"name": "parent-app", "parent": "grand-parent-app.yml"},
            new={"name": "parent-app", "parent": "grand-parent-app.yml"},
        )
        .register_raw_diff(
            path="grand-parent-app.yml",
            old={"name": "grant-parent-app", "parent": "app.yml"},
            new={"name": "grant-parent-app", "parent": "app.yml"},
        ),
    )

    app_hierarchy_change_type_processor = processors[app_hierarchy_change_type.name]
    contexts = app_hierarchy_change_type_processor.find_context_file_refs(
        app_change.fileref, app_change.old, app_change.new, set()
    )
    ownership_dict = {ro.owned_file_ref.path: ro for ro in contexts}
    assert len(ownership_dict) == 3

    assert "app.yml" in ownership_dict
    assert ownership_dict["app.yml"].change_type.name == app_hierarchy_change_type.name

    assert "parent-app.yml" in ownership_dict
    assert (
        ownership_dict["parent-app.yml"].change_type.name
        == app_hierarchy_change_type.name
    )

    assert "grand-parent-app.yml" in ownership_dict
    assert (
        ownership_dict["grand-parent-app.yml"].change_type.name
        == app_hierarchy_change_type.name
    )
