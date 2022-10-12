from dataclasses import dataclass
from typing import Any, Optional
from reconcile.change_owners.diff import (
    SHA256SUM_FIELD_NAME,
    Diff,
    DiffType,
    deepdiff_path_to_jsonpath,
)
from reconcile.change_owners.change_owners import (
    manage_conditional_label,
)
from reconcile.change_owners.self_service_roles import (
    cover_changes_with_self_service_roles,
)
from reconcile.change_owners.decision import (
    get_approver_decisions_from_mr_comments,
    apply_decisions_to_changes,
    DecisionCommand,
    Decision,
)
from reconcile.change_owners.change_types import (
    BundleFileChange,
    BundleFileType,
    ChangeTypeContext,
    Approver,
    FileRef,
    DiffCoverage,
    build_change_type_processor,
    create_bundle_file_change,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeChangeDetectorV1,
    ChangeTypeV1,
)
from reconcile.gql_definitions.change_owners.queries import self_service_roles
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    DatafileObjectV1,
    RoleV1,
    SelfServiceConfigV1,
    UserV1,
    BotV1,
)

from .fixtures import Fixtures

import pytest
import copy
import jsonpath_ng
import jsonpath_ng.ext
from jsonpath_ng.exceptions import JsonPathParserError

fxt = Fixtures("change_owners")


@dataclass
class TestFile:
    filepath: str
    fileschema: str
    filetype: str
    content: dict[str, Any]

    def file_ref(self) -> FileRef:
        return FileRef(
            path=self.filepath,
            schema=self.fileschema,
            file_type=BundleFileType[self.filetype.upper()],
        )

    def create_bundle_change(
        self, jsonpath_patches: dict[str, Any]
    ) -> BundleFileChange:
        new_content = copy.deepcopy(self.content)
        if jsonpath_patches:
            for jp, v in jsonpath_patches.items():
                e = jsonpath_ng.ext.parse(jp)
                e.update(new_content, v)
        bundle_file_change = create_bundle_file_change(
            path=self.filepath,
            schema=self.fileschema,
            file_type=BundleFileType[self.filetype.upper()],
            old_file_content=self.content,
            new_file_content=new_content,
        )
        assert bundle_file_change
        return bundle_file_change


def load_change_type(path: str) -> ChangeTypeV1:
    content = fxt.get_anymarkup(path)
    return ChangeTypeV1(**content)


def load_self_service_roles(path: str) -> list[RoleV1]:
    roles = fxt.get_anymarkup(path)["self_service_roles"]
    return [RoleV1(**r) for r in roles]


def build_role(
    name: str,
    change_type_name: str,
    datafiles: Optional[list[DatafileObjectV1]],
    users: Optional[list[str]] = None,
    bots: Optional[list[str]] = None,
) -> RoleV1:
    return RoleV1(
        name=name,
        path=f"/role/{name}.yaml",
        self_service=[
            SelfServiceConfigV1(
                change_type=self_service_roles.ChangeTypeV1(
                    name=change_type_name,
                ),
                datafiles=datafiles,
                resources=None,
            )
        ],
        users=[
            UserV1(org_username=u, tag_on_merge_requests=False) for u in users or []
        ],
        bots=[BotV1(org_username=b) for b in bots or []],
    )


@pytest.fixture
def saas_file_changetype() -> ChangeTypeV1:
    return load_change_type("changetype_saas_file.yaml")


@pytest.fixture
def role_member_change_type() -> ChangeTypeV1:
    return load_change_type("changetype_role_member.yaml")


@pytest.fixture
def cluster_owner_change_type() -> ChangeTypeV1:
    return load_change_type("changetype_cluster_owner.yml")


@pytest.fixture
def secret_promoter_change_type() -> ChangeTypeV1:
    return load_change_type("changetype_secret_promoter.yaml")


@pytest.fixture
def change_types() -> list[ChangeTypeV1]:
    return [saas_file_changetype(), role_member_change_type()]


@pytest.fixture
def saas_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_saas_file.yaml"))


@pytest.fixture
def user_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_user.yaml"))


@pytest.fixture
def namespace_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_namespace.yaml"))


@pytest.fixture
def rds_defaults_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("resourcefile_rds_defaults.yaml"))


#
# testcases for context file refs extraction from bundle changes
#


def test_extract_context_file_refs_from_bundle_change(
    saas_file_changetype: ChangeTypeV1, saas_file: TestFile
):
    """
    in this testcase, a changed datafile matches directly the context schema
    of the change type, so the change type is directly relevant for the changed
    datafile
    """
    bundle_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    file_refs = bundle_change.extract_context_file_refs(saas_file_changetype)
    assert file_refs == [saas_file.file_ref()]


def test_extract_context_file_refs_from_bundle_change_schema_mismatch(
    saas_file_changetype: ChangeTypeV1, saas_file: TestFile
):
    """
    in this testcase, the schema of the bundle change and the schema of the
    change types do not match and hence no file context is extracted.
    """
    saas_file.fileschema = "/some/other/schema.yml"
    bundle_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    file_refs = bundle_change.extract_context_file_refs(saas_file_changetype)
    assert not file_refs


def test_extract_context_file_refs_selector(
    cluster_owner_change_type: ChangeTypeV1,
):
    """
    this testcase extracts the context file based on the change types context
    selector
    """
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
    file_refs = namespace_change.extract_context_file_refs(cluster_owner_change_type)
    assert file_refs == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/openshift/cluster-1.yml",
            path=cluster,
        )
    ]


def test_extract_context_file_refs_in_list_added_selector(
    role_member_change_type: ChangeTypeV1,
):
    """
    in this testcase, a changed datafile does not directly belong to the change
    type, because the context schema does not match (change type reacts to roles,
    while the changed datafile is a user). but the change type defines a context
    extraction section that feels responsible for user files and extracts the
    relevant context, the role, from the users role section, looking out for added
    roles.
    """
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
    file_refs = user_change.extract_context_file_refs(role_member_change_type)
    assert file_refs == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/access/roles-1.yml",
            path=new_role,
        )
    ]


def test_extract_context_file_refs_in_list_removed_selector(
    role_member_change_type: ChangeTypeV1,
):
    """
    this testcase is similar to previous one, but detects removed contexts (e.g
    roles in this example) as the relevant context to extract.
    """
    role_member_change_type.changes[0].context.when = "removed"  # type: ignore
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
    file_refs = user_change.extract_context_file_refs(role_member_change_type)
    assert file_refs == [
        FileRef(
            file_type=BundleFileType.DATAFILE,
            schema="/access/roles-1.yml",
            path=existing_role,
        )
    ]


def test_extract_context_file_refs_in_list_selector_change_schema_mismatch(
    role_member_change_type: ChangeTypeV1,
):
    """
    in this testcase, the changeSchema section of the change types changes does
    not match the bundle change.
    """
    datafile_change = create_bundle_file_change(
        path="/somepath.yml",
        schema="/some/other/schema.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={"field": "old-value"},
        new_file_content={"field": "new-value"},
    )
    assert datafile_change
    file_refs = datafile_change.extract_context_file_refs(role_member_change_type)
    assert not file_refs


#
# deep diff path translation
#


@pytest.mark.parametrize(
    "deep_diff_path,expected_json_path",
    [
        ("root['one']['two']['three']", "one.two.three"),
        (
            "root['resourceTemplates'][0]['targets'][0]['ref']",
            "resourceTemplates.[0].targets.[0].ref",
        ),
        ("root", "$"),
    ],
)
def test_deepdiff_path_to_jsonpath(deep_diff_path, expected_json_path):
    assert str(deepdiff_path_to_jsonpath(deep_diff_path)) == expected_json_path


def test_deepdiff_invalid():
    with pytest.raises(ValueError):
        deepdiff_path_to_jsonpath("something_invalid")


#
# change type processor validations
#


def test_change_type_processor_building_unsupported_provider(
    secret_promoter_change_type: ChangeTypeV1,
):
    secret_promoter_change_type.changes[0] = ChangeTypeChangeDetectorV1(
        provider="unsupported-provider", changeSchema=None, context=None
    )
    with pytest.raises(ValueError):
        build_change_type_processor(secret_promoter_change_type)


def test_change_type_processor_building_invalid_jsonpaths(
    secret_promoter_change_type: ChangeTypeV1,
):
    secret_promoter_change_type.changes[0].json_path_selectors[  # type: ignore
        0
    ] = "invalid-jsonpath/selector"
    with pytest.raises(JsonPathParserError):
        build_change_type_processor(secret_promoter_change_type)


#
# change type processor find allowed changed paths
#


def test_change_type_processor_allowed_paths_simple(
    role_member_change_type: ChangeTypeV1, user_file: TestFile
):
    changed_user_file = user_file.create_bundle_change(
        {"roles[0]": {"$ref": "some-role"}}
    )
    processor = build_change_type_processor(role_member_change_type)
    paths = processor.allowed_changed_paths(
        changed_user_file.fileref, changed_user_file.new
    )

    assert paths == ["roles"]


def test_change_type_processor_allowed_paths_conditions(
    secret_promoter_change_type: ChangeTypeV1, namespace_file: TestFile
):
    changed_namespace_file = namespace_file.create_bundle_change(
        {"openshiftResources[1].version": 2}
    )
    processor = build_change_type_processor(secret_promoter_change_type)
    paths = processor.allowed_changed_paths(
        changed_namespace_file.fileref, changed_namespace_file.new
    )

    assert paths == ["openshiftResources.[1].version"]


#
# bundle changes diff detection
#


def test_bundle_change_diff_value_changed():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.DATAFILE,
        old_file_content={"field": "old_value"},
        new_file_content={"field": "new_value"},
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "old_value"
    assert bundle_change.diff_coverage[0].diff.new == "new_value"


def test_bundle_change_diff_value_changed_deep():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.DATAFILE,
        old_file_content={"parent": {"children": [{"age": 1}]}},
        new_file_content={"parent": {"children": [{"age": 2}]}},
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "parent.children.[0].age"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == 1
    assert bundle_change.diff_coverage[0].diff.new == 2


def test_bundle_change_diff_value_changed_multiple_in_iterable():
    """
    this testscenario searches shows how changes can be detected in a list,
    when objects with identifiers and objects without are mixed and shuffled
    """
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
                {
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 2,
                    "__identifier": "secret-2",
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val1", "var2": "val2"},
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val3", "var2": "val4"},
                },
            ],
        },
        new_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 1,
                    "__identifier": "secret-2",
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val1", "var2": "new_val"},
                },
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 2,
                    "__identifier": "secret-1",
                },
                {
                    "provider": "resource-template",
                    "path": "res-1",
                    "variables": {"var1": "val3", "var2": "val4"},
                },
            ],
        },
    )
    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("openshiftResources.[1].version"),
                diff_type=DiffType.CHANGED,
                old=2,
                new=1,
            ),
            coverage=[],
        ),
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("openshiftResources.[2].variables.var2"),
                diff_type=DiffType.CHANGED,
                old="val2",
                new="new_val",
            ),
            coverage=[],
        ),
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("openshiftResources.[0].version"),
                diff_type=DiffType.CHANGED,
                old=1,
                new=2,
            ),
            coverage=[],
        ),
    ]
    assert bundle_change.diff_coverage == expected


def test_bundle_change_diff_property_added():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
            ],
        },
        new_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                    "new_field": "value",
                },
            ],
        },
    )
    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("openshiftResources.[0].new_field"),
                diff_type=DiffType.ADDED,
                old=None,
                new="value",
            ),
            coverage=[],
        )
    ]
    assert bundle_change.diff_coverage == expected


def test_bundle_change_diff_property_removed():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                    "old_field": "value",
                },
            ],
        },
        new_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
            ],
        },
    )
    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("openshiftResources.[0].old_field"),
                diff_type=DiffType.REMOVED,
                old="value",
                new=None,
            ),
            coverage=[],
        )
    ]
    assert bundle_change.diff_coverage == expected


def test_bundle_change_diff_item_added():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
            ],
        },
        new_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 2,
                    "__identifier": "secret-2",
                },
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
            ],
        },
    )
    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("openshiftResources.[0]"),
                diff_type=DiffType.ADDED,
                old=None,
                new={
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 2,
                    "__identifier": "secret-2",
                },
            ),
            coverage=[],
        )
    ]
    assert bundle_change.diff_coverage == expected


def test_bundle_change_diff_item_removed():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
                {
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 2,
                    "__identifier": "secret-2",
                },
            ],
        },
        new_file_content={
            "$schema": "/openshift/namespace-1.yml",
            "openshiftResources": [
                {
                    "provider": "vault-secret",
                    "path": "path-2",
                    "version": 2,
                    "__identifier": "secret-2",
                },
            ],
        },
    )
    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("openshiftResources.[0]"),
                diff_type=DiffType.REMOVED,
                old={
                    "provider": "vault-secret",
                    "path": "path-1",
                    "version": 1,
                    "__identifier": "secret-1",
                },
                new=None,
            ),
            coverage=[],
        )
    ]
    assert bundle_change.diff_coverage == expected


def test_bundle_change_diff_item_replaced():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "an_item"},
                {"$ref": "old_item"},
                {"$ref": "another_item"},
            ],
        },
        new_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "an_item"},
                {"$ref": "new_item"},
                {"$ref": "another_item"},
            ],
        },
    )
    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("roles.[1].'$ref'"),
                diff_type=DiffType.CHANGED,
                old="old_item",
                new="new_item",
            ),
            coverage=[],
        )
    ]
    assert bundle_change.diff_coverage == expected


def test_bundle_change_diff_ref_item_multiple_consecutive_replaced():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "1"},
                {"$ref": "2"},
                {"$ref": "3"},
                {"$ref": "4"},
                {"$ref": "5"},
                {"$ref": "6"},
            ],
        },
        new_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "1"},
                {"$ref": "2"},
                {"$ref": "changed"},
                {"$ref": "changed as well"},
                {"$ref": "5"},
                {"$ref": "6"},
            ],
        },
    )

    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("roles.[2]"),
                diff_type=DiffType.CHANGED,
                old={"$ref": "3"},
                new={"$ref": "changed"},
            ),
            coverage=[],
        ),
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("roles.[3]"),
                diff_type=DiffType.CHANGED,
                old={"$ref": "4"},
                new={"$ref": "changed as well"},
            ),
            coverage=[],
        ),
    ]
    diffs = sorted(bundle_change.diff_coverage, key=lambda d: str(d.diff.path))
    assert diffs == expected


def test_bundle_change_diff_ref_item_multiple_replaced():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "1"},
                {"$ref": "2"},
                {"$ref": "3"},
                {"$ref": "4"},
                {"$ref": "5"},
                {"$ref": "6"},
                {"$ref": "7"},
            ],
        },
        new_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "1"},
                {"$ref": "2"},
                {"$ref": "changed"},
                {"$ref": "4"},
                {"$ref": "changed as well"},
                {"$ref": "6"},
                {"$ref": "7"},
            ],
        },
    )

    assert bundle_change

    expected = [
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("roles.[2]"),
                diff_type=DiffType.CHANGED,
                old={"$ref": "3"},
                new={"$ref": "changed"},
            ),
            coverage=[],
        ),
        DiffCoverage(
            diff=Diff(
                path=jsonpath_ng.parse("roles.[4]"),
                diff_type=DiffType.CHANGED,
                old={"$ref": "5"},
                new={"$ref": "changed as well"},
            ),
            coverage=[],
        ),
    ]
    diffs = sorted(bundle_change.diff_coverage, key=lambda d: str(d.diff.path))
    assert diffs == expected


def test_bundle_change_diff_item_reorder():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="/access/user-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "an_item"},
                {"$ref": "reorder_item"},
                {"$ref": "another_item"},
            ],
        },
        new_file_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "an_item"},
                {"$ref": "another_item"},
                {"$ref": "reorder_item"},
            ],
        },
    )

    assert not bundle_change


def test_bundle_change_diff_resourcefile_without_schema():
    bundle_change = create_bundle_file_change(
        path="path",
        schema=None,
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content="field: old_value",
        new_file_content="field: new_value",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "field: old_value"
    assert bundle_change.diff_coverage[0].diff.new == "field: new_value"


def test_bundle_change_diff_resourcefile_with_schema():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content="""
        field: old_value
        """,
        new_file_content="""
        field: new_value
        """,
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "old_value"
    assert bundle_change.diff_coverage[0].diff.new == "new_value"


def test_bundle_change_diff_resourcefile_with_schema_unparsable():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content="somethingsomething",
        new_file_content="somethingsomething_different",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "somethingsomething"
    assert bundle_change.diff_coverage[0].diff.new == "somethingsomething_different"


def test_bundle_change_resource_file_added():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content=None,
        new_file_content="new content",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.ADDED
    assert bundle_change.diff_coverage[0].diff.old is None
    assert bundle_change.diff_coverage[0].diff.new == "new content"


def test_bundle_change_resource_file_removed():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content="old content",
        new_file_content=None,
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.REMOVED
    assert bundle_change.diff_coverage[0].diff.old == "old content"
    assert bundle_change.diff_coverage[0].diff.new is None


def test_bundle_change_resource_file_dict_value_added():
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content='{"field": {}}',
        new_file_content='{"field": {"new_field": "new_value"}}',
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "field.new_field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.ADDED
    assert bundle_change.diff_coverage[0].diff.old is None
    assert bundle_change.diff_coverage[0].diff.new == "new_value"


def test_only_checksum_changed():
    """
    only the checksum changed
    """
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.DATAFILE,
        old_file_content={"field": "value", SHA256SUM_FIELD_NAME: "old_checksum"},
        new_file_content={"field": "value", SHA256SUM_FIELD_NAME: "new_checksum"},
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == SHA256SUM_FIELD_NAME
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "old_checksum"
    assert bundle_change.diff_coverage[0].diff.new == "new_checksum"


def test_checksum_and_content_changed():
    """
    the checksum changed because a real field changed
    """
    bundle_change = create_bundle_file_change(
        path="path",
        schema="schema",
        file_type=BundleFileType.DATAFILE,
        old_file_content={"field": "value1", SHA256SUM_FIELD_NAME: "old_checksum"},
        new_file_content={"field": "value2", SHA256SUM_FIELD_NAME: "new_checksum"},
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "value1"
    assert bundle_change.diff_coverage[0].diff.new == "value2"


#
# processing change coverage on a change type context
#


def test_cover_changes_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: TestFile
):
    saas_file_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    ctx = ChangeTypeContext(
        change_type_processor=build_change_type_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
    )
    saas_file_change.cover_changes(ctx)

    assert not list(saas_file_change.uncovered_changes())
    assert saas_file_change.all_changes_covered()
    assert saas_file_change.diff_coverage[0].is_covered()
    assert saas_file_change.diff_coverage[0].coverage == [ctx]


def test_uncovered_change_because_change_type_is_disabled(
    saas_file_changetype: ChangeTypeV1, saas_file: TestFile
):
    saas_file_changetype.disabled = True
    saas_file_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    ctx = ChangeTypeContext(
        change_type_processor=build_change_type_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
    )
    saas_file_change.cover_changes(ctx)
    uncoverd_changes = list(saas_file_change.uncovered_changes())
    assert uncoverd_changes
    assert not saas_file_change.all_changes_covered()
    assert not uncoverd_changes[0].is_covered()
    assert uncoverd_changes[0].coverage[0].disabled


def test_uncovered_change_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: TestFile
):
    saas_file_change = saas_file.create_bundle_change({"name": "new-name"})
    ctx = ChangeTypeContext(
        change_type_processor=build_change_type_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
    )
    saas_file_change.cover_changes(ctx)
    assert all(not dc.is_covered() for dc in saas_file_change.diff_coverage)


def test_partially_covered_change_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: TestFile
):
    ref_update_path = "resourceTemplates.[0].targets.[0].ref"
    saas_file_change = saas_file.create_bundle_change(
        {ref_update_path: "new-ref", "name": "new-name"}
    )
    ref_update_diff = next(
        d for d in saas_file_change.diff_coverage if str(d.diff.path) == ref_update_path
    )
    ctx = ChangeTypeContext(
        change_type_processor=build_change_type_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
    )

    covered_diffs = saas_file_change.cover_changes(ctx)
    assert [ref_update_diff.diff] == covered_diffs


def test_root_change_type(cluster_owner_change_type: ChangeTypeV1, saas_file: TestFile):
    namespace_change = create_bundle_file_change(
        path="/my/namespace.yml",
        schema="/openshift/namespace-1.yml",
        file_type=BundleFileType.DATAFILE,
        old_file_content={
            "cluster": {
                "$ref": "cluster.yml",
            },
            "networkPolicy": [
                {"$ref": "networkpolicy.yml"},
            ],
        },
        new_file_content={
            "cluster": {
                "$ref": "cluster.yml",
            },
            "networkPolicy": [
                {"$ref": "networkpolicy.yml"},
                {"$ref": "new-networkpolicy.yml"},
            ],
        },
    )
    assert namespace_change
    ctx = ChangeTypeContext(
        change_type_processor=build_change_type_processor(cluster_owner_change_type),
        context="RoleV1 - some-role",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
    )

    covered_diffs = namespace_change.cover_changes(ctx)
    assert covered_diffs


#
# test change coverage
#


def test_change_coverage(
    secret_promoter_change_type: ChangeTypeV1,
    namespace_file: TestFile,
    role_member_change_type: ChangeTypeV1,
    user_file: TestFile,
):
    role_approver_user = "the-one-that-approves-roles"
    team_role_path = "/team-role.yml"
    role_approval_role = build_role(
        name="team-role",
        change_type_name=role_member_change_type.name,
        datafiles=[
            DatafileObjectV1(datafileSchema="/access/role-1.yml", path=team_role_path)
        ],
        users=[role_approver_user],
    )

    secret_approver_user = "the-one-that-approves-secret-promotions"
    secret_promoter_role = build_role(
        name="secret-promoter-role",
        change_type_name=secret_promoter_change_type.name,
        datafiles=[
            DatafileObjectV1(
                datafileSchema=namespace_file.fileschema,
                path=namespace_file.filepath,
            )
        ],
        users=[secret_approver_user],
    )

    bundle_changes = [
        # create a datafile change by patching the role
        user_file.create_bundle_change({"roles[0]": {"$ref": team_role_path}}),
        # create a datafile change by bumping a secret version
        namespace_file.create_bundle_change({"openshiftResources[1].version": 2}),
    ]

    cover_changes_with_self_service_roles(
        roles=[role_approval_role, secret_promoter_role],
        change_type_processors=[
            build_change_type_processor(role_member_change_type),
            build_change_type_processor(secret_promoter_change_type),
        ],
        bundle_changes=bundle_changes,
    )

    for bc in bundle_changes:
        for d in bc.diff_coverage:
            if str(d.diff.path) == "roles.[0].$ref":
                expected_approver = role_approver_user
            elif str(d.diff.path) == "openshiftResources.[1].version":
                expected_approver = secret_approver_user
            else:
                pytest.fail(f"unexpected change path {str(d.diff.path)}")
            assert len(d.coverage) == 1
            assert len(d.coverage[0].approvers) == 1
            assert d.coverage[0].approvers[0].org_username == expected_approver


#
# test MR decision comment parsing
#


def test_approver_decision_approve_and_hold():
    comments = [
        {
            "username": "user-1",
            "body": ("nice\n" f"{DecisionCommand.APPROVED.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-2",
            "body": (f"{DecisionCommand.HOLD.value}\n" "oh wait... big problems"),
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=True, hold=False),
        "user-2": Decision(approve=False, hold=True),
    }


def test_approver_approve_and_cancel():
    comments = [
        {
            "username": "user-1",
            "body": ("nice\n" f"{DecisionCommand.APPROVED.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-1",
            "body": (
                f"{DecisionCommand.CANCEL_APPROVED.value}\n"
                "oh wait... changed my mind"
            ),
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=False, hold=False),
    }


def test_approver_hold_and_unhold():
    comments = [
        {
            "username": "user-1",
            "body": ("wait...\n" f"{DecisionCommand.HOLD.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-1",
            "body": (
                f"{DecisionCommand.CANCEL_HOLD.value}\n" "oh never mind... keep going"
            ),
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=False, hold=False),
    }


def test_unordered_approval_comments():
    comments = [
        {
            "username": "user-1",
            "body": (
                f"{DecisionCommand.CANCEL_HOLD.value}\n" "oh never mind... keep going"
            ),
            "created_at": "2020-01-02T00:00:00Z",
        },
        {
            "username": "user-1",
            "body": ("wait...\n" f"{DecisionCommand.HOLD.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=False, hold=False),
    }


def test_approval_comments_none_body():
    comments = [
        {
            "username": "user-1",
            "body": None,
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert not get_approver_decisions_from_mr_comments(comments)


#
# test decide on changes
#


def test_change_decision(saas_file_changetype: ChangeTypeV1):
    yea_user = "yea-sayer"
    nay_sayer = "nay-sayer"
    change = create_bundle_file_change(
        file_type=BundleFileType.DATAFILE,
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_file_content={"foo": "bar"},
        new_file_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1 and change.diff_coverage[0]
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=build_change_type_processor(saas_file_changetype),
            context="something-something",
            approvers=[
                Approver(org_username=yea_user, tag_on_merge_requests=False),
                Approver(org_username=nay_sayer, tag_on_merge_requests=False),
            ],
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={
            yea_user: Decision(approve=True, hold=False),
            nay_sayer: Decision(approve=False, hold=True),
        },
        changes=[change],
    )

    assert change_decision[0].decision.approve
    assert change_decision[0].decision.hold
    assert change_decision[0].diff == change.diff_coverage[0].diff
    assert change_decision[0].file == change.fileref

    # disable the change_type and ensure that the approval has no effect
    saas_file_changetype.disabled = True
    change_decision = apply_decisions_to_changes(
        approver_decisions={
            yea_user: Decision(approve=True, hold=False),
            nay_sayer: Decision(approve=False, hold=True),
        },
        changes=[change],
    )

    assert not change_decision[0].decision.approve
    assert not change_decision[0].decision.hold


#
# test label management
#


def test_label_management_condition_true():
    assert ["existing-label", "true-label"] == manage_conditional_label(
        labels=["existing-label"],
        condition=True,
        true_label="true-label",
        false_label="false-label",
        dry_run=False,
    )

    assert ["existing-label"] == manage_conditional_label(
        labels=["existing-label"],
        condition=True,
        true_label="true-label",
        false_label="false-label",
        dry_run=True,
    )


def test_label_management_condition_false():
    assert ["existing-label", "false-label"] == manage_conditional_label(
        labels=["existing-label"],
        condition=False,
        true_label="true-label",
        false_label="false-label",
        dry_run=False,
    )

    assert ["existing-label"] == manage_conditional_label(
        labels=["existing-label"],
        condition=False,
        true_label="true-label",
        false_label="false-label",
        dry_run=True,
    )


def test_label_management_true_to_false():
    assert ["existing-label", "false-label"] == manage_conditional_label(
        labels=["existing-label", "true-label"],
        condition=False,
        true_label="true-label",
        false_label="false-label",
        dry_run=False,
    )

    assert ["existing-label", "true-label"] == manage_conditional_label(
        labels=["existing-label", "true-label"],
        condition=False,
        true_label="true-label",
        false_label="false-label",
        dry_run=True,
    )


def test_label_management_false_to_true():
    assert ["existing-label", "true-label"] == manage_conditional_label(
        labels=["existing-label", "false-label"],
        condition=True,
        true_label="true-label",
        false_label="false-label",
        dry_run=False,
    )

    assert ["existing-label", "false-label"] == manage_conditional_label(
        labels=["existing-label", "false-label"],
        condition=True,
        true_label="true-label",
        false_label="false-label",
        dry_run=True,
    )


#
# DiffCoverage tests
#


def test_diff_no_coverage():
    dc = DiffCoverage(diff=None, coverage=[])  # type: ignore
    assert not dc.is_covered()


def test_diff_covered(saas_file_changetype: ChangeTypeV1):
    dc = DiffCoverage(
        diff=None,  # type: ignore
        coverage=[
            ChangeTypeContext(
                change_type_processor=build_change_type_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                approvers=[],
            ),
        ],
    )
    assert dc.is_covered()


def test_diff_covered_many(
    saas_file_changetype: ChangeTypeV1, role_member_change_type: ChangeTypeV1
):
    dc = DiffCoverage(
        diff=None,  # type: ignore
        coverage=[
            ChangeTypeContext(
                change_type_processor=build_change_type_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                approvers=[],
            ),
            ChangeTypeContext(
                change_type_processor=build_change_type_processor(
                    role_member_change_type
                ),
                context="RoleV1 - some-role",
                approvers=[],
            ),
        ],
    )
    assert dc.is_covered()


def test_diff_covered_partially_disabled(
    saas_file_changetype: ChangeTypeV1, role_member_change_type: ChangeTypeV1
):
    role_member_change_type.disabled = True
    dc = DiffCoverage(
        diff=None,  # type: ignore
        coverage=[
            ChangeTypeContext(
                change_type_processor=build_change_type_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                approvers=[],
            ),
            ChangeTypeContext(
                change_type_processor=build_change_type_processor(
                    role_member_change_type
                ),
                context="RoleV1 - some-role",
                approvers=[],
            ),
        ],
    )
    assert dc.is_covered()


def test_diff_no_coverage_all_disabled(
    saas_file_changetype: ChangeTypeV1, role_member_change_type: ChangeTypeV1
):
    role_member_change_type.disabled = True
    saas_file_changetype.disabled = True
    dc = DiffCoverage(
        diff=None,  # type: ignore
        coverage=[
            ChangeTypeContext(
                change_type_processor=build_change_type_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                approvers=[],
            ),
            ChangeTypeContext(
                change_type_processor=build_change_type_processor(
                    role_member_change_type
                ),
                context="RoleV1 - some-role",
                approvers=[],
            ),
        ],
    )
    assert not dc.is_covered()
