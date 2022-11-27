import pytest

from reconcile.change_owners.change_types import (
    find_context_file_refs,
    build_change_type_processor,
    create_bundle_file_change,
    BundleFileType,
    FileRef,
)
from reconcile.test.change_owners.utils import (
    TestFile,
    MockQuerier,
    build_change_role_member_changetype,
    build_saas_file_target_cluster_owner_changetype,
    build_saas_file_changetype,
    build_cluster_owner_changetype,
)
from reconcile.test.fixtures import Fixtures
from jsonpath_ng.exceptions import JSONPathError

#
# testcases for context file refs extraction from bundle changes
#


fxt = Fixtures("change_owners")


@pytest.fixture
def saas_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_saas_file.yaml"))


def test_extract_context_file_refs_from_bundle_change(saas_file: TestFile):
    """
    in this testcase, a changed datafile matches directly the context schema
    of the change type, so the change type is directly relevant for the changed
    datafile
    """
    saas_file_changetype = build_saas_file_changetype()
    bundle_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    file_refs = find_context_file_refs(
        bundle_change=bundle_change,
        change_type=build_change_type_processor(saas_file_changetype),
        comparision_querier=MockQuerier(),
        querier=MockQuerier(),
    )
    assert file_refs == [saas_file.file_ref()]


def test_extract_context_file_refs_from_bundle_change_schema_mismatch(
    saas_file: TestFile,
):
    """
    in this testcase, the schema of the bundle change and the schema of the
    change types do not match and hence no file context is extracted.
    """
    saas_file_changetype = build_saas_file_changetype()
    saas_file.fileschema = "/some/other/schema.yml"
    bundle_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    file_refs = find_context_file_refs(
        bundle_change=bundle_change,
        change_type=build_change_type_processor(saas_file_changetype),
        comparision_querier=MockQuerier(),
        querier=MockQuerier(),
    )
    assert not file_refs


def test_extract_context_file_refs_selector():
    """
    this testcase extracts the context file based on the change types context
    selector
    """
    cluster_owner_changetype = build_cluster_owner_changetype()
    cluster = "/my/cluster.yml"
    namespace_change = create_bundle_file_change(
        path="/my/namespace.yml",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "the_change": "does not matter in this test",
            "cluster": {
                "$ref": cluster,
            },
        },
        new_file_content={
            "cluster": {
                "$ref": cluster,
            },
        },
    )
    assert namespace_change
    file_refs = find_context_file_refs(
        bundle_change=namespace_change,
        change_type=build_change_type_processor(cluster_owner_changetype),
        comparision_querier=MockQuerier(),
        querier=MockQuerier(),
    )
    assert file_refs == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/openshift/cluster-1.yml",
            path=cluster,
        )
    ]


def test_extract_context_file_refs_in_list_added_selector():
    """
    in this testcase, a changed datafile does not directly belong to the change
    type, because the context schema does not match (change type reacts to roles,
    while the changed datafile is a user). but the change type defines a context
    extraction section that feels responsible for user files and extracts the
    relevant context, the role, from the users role section, looking out for added
    roles.
    """
    change_role_member_changetype = build_change_role_member_changetype()
    new_role = "/role/new.yml"
    user_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "roles": [{"$ref": "/role/existing.yml"}],
        },
        new_file_content={
            "roles": [{"$ref": "/role/existing.yml"}, {"$ref": new_role}],
        },
    )
    assert user_change
    file_refs = find_context_file_refs(
        bundle_change=user_change,
        change_type=build_change_type_processor(change_role_member_changetype),
        comparision_querier=MockQuerier(),
        querier=MockQuerier(),
    )
    assert file_refs == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/access/role-1.yml",
            path=new_role,
        )
    ]


def test_extract_context_file_refs_in_list_removed_selector():
    """
    this testcase is similar to previous one, but detects removed contexts (e.g
    roles in this example) as the relevant context to extract.
    """
    change_role_member_changetype = build_change_role_member_changetype()
    change_role_member_changetype.changes[0].context.when = "removed"  # type: ignore
    existing_role = "/role/existing.yml"
    new_role = "/role/new.yml"
    user_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "roles": [{"$ref": existing_role}],
        },
        new_file_content={
            "roles": [{"$ref": new_role}],
        },
    )
    assert user_change
    file_refs = find_context_file_refs(
        bundle_change=user_change,
        change_type=build_change_type_processor(change_role_member_changetype),
        comparision_querier=MockQuerier(),
        querier=MockQuerier(),
    )
    assert file_refs == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/access/role-1.yml",
            path=existing_role,
        )
    ]


def test_extract_context_file_refs_in_list_selector_change_schema_mismatch():
    """
    in this testcase, the changeSchema section of the change types changes does
    not match the bundle change.
    """
    change_role_member_changetype = build_change_role_member_changetype()
    datafile_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/some/other/schema.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={"field": "old-value"},
        new_file_content={"field": "new-value"},
    )
    assert datafile_change
    file_refs = find_context_file_refs(
        bundle_change=datafile_change,
        change_type=build_change_type_processor(change_role_member_changetype),
        comparision_querier=MockQuerier(),
        querier=MockQuerier(),
    )
    assert not file_refs


def test_extract_context_file_refs_gql_jsonpath_selector(saas_file: TestFile):
    """ """
    saas_file_target_cluster_owner_changetype = (
        build_saas_file_target_cluster_owner_changetype()
    )
    bundle_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    file_refs = find_context_file_refs(
        bundle_change=bundle_change,
        change_type=build_change_type_processor(
            saas_file_target_cluster_owner_changetype
        ),
        comparision_querier=MockQuerier([{}]),
        querier=MockQuerier(
            [
                {
                    "saas_files_v2": [
                        {
                            "path": bundle_change.fileref.path,
                            "resourceTemplates": [
                                {
                                    "targets": [
                                        {
                                            "namespace": {
                                                "cluster": {"path": "my-cluster.yml"}
                                            }
                                        }
                                    ]
                                },
                            ],
                        }
                    ]
                }
            ]
        ),
    )
    assert file_refs == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/openshift/cluster-1.yml",
            path="my-cluster.yml",
        )
    ]


def test_extract_context_file_refs_unknown_selector_protocol(saas_file: TestFile):
    saas_file_target_cluster_owner_changetype = (
        build_saas_file_target_cluster_owner_changetype()
    )
    saas_file_target_cluster_owner_changetype.changes[0].context.selector = "unknown://a.b.c"  # type: ignore
    bundle_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    with pytest.raises(ValueError):
        find_context_file_refs(
            bundle_change=bundle_change,
            change_type=build_change_type_processor(
                saas_file_target_cluster_owner_changetype
            ),
            comparision_querier=MockQuerier(),
            querier=MockQuerier(),
        )


def test_change_type_context_validation_invalid_jsonpath():
    saas_file_target_cluster_owner_changetype = (
        build_saas_file_target_cluster_owner_changetype()
    )
    saas_file_target_cluster_owner_changetype.changes[0].context.selector = "gql+jsonpath://a/b"  # type: ignore
    with pytest.raises(JSONPathError):
        build_change_type_processor(saas_file_target_cluster_owner_changetype)


def test_change_type_context_validation_invalid_protocol():
    saas_file_target_cluster_owner_changetype = (
        build_saas_file_target_cluster_owner_changetype()
    )
    saas_file_target_cluster_owner_changetype.changes[0].context.selector = "invalid://a.b"  # type: ignore
    with pytest.raises(ValueError):
        build_change_type_processor(saas_file_target_cluster_owner_changetype)
