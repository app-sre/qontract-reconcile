import jsonpath_ng
import jsonpath_ng.ext
import pytest

from reconcile.change_owners.bundle import BundleFileType
from reconcile.change_owners.change_types import DiffCoverage
from reconcile.change_owners.changes import create_bundle_file_change
from reconcile.change_owners.diff import (
    SHA256SUM_FIELD_NAME,
    Diff,
    DiffType,
    deepdiff_path_to_jsonpath,
)

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


def test_deepdiff_path_element_with_dot():
    assert (
        str(deepdiff_path_to_jsonpath("root['data']['main.yaml']"))
        == "data.'main.yaml'"
    )


#
# bundle changes diff detection
#


def test_bundle_change_diff_value_changed():
    """
    detect a change on a top level field
    """
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
    """
    detect a change deeper in the object tree
    """
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
    this testscenario shows how changes can be detected in a list,
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
    """
    this test scenario show how a newly added property is correctly
    detected if the containing object has a clear identity.
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
    """
    this test scenario show how a removed property is correctly
    detected if the containing object has a clear identity.
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


def test_bundle_change_diff_resourcefile_without_schema_unparsable():
    bundle_change = create_bundle_file_change(
        path="path",
        schema=None,
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content="something_old",
        new_file_content="something_new",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "something_old"
    assert bundle_change.diff_coverage[0].diff.new == "something_new"


def test_bundle_change_diff_resourcefile_without_schema_parsable():
    bundle_change = create_bundle_file_change(
        path="path",
        schema=None,
        file_type=BundleFileType.RESOURCEFILE,
        old_file_content="field: old_value",
        new_file_content="field: new_value",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert bundle_change.old == {"field": "old_value"}
    assert bundle_change.new == {"field": "new_value"}
    assert str(bundle_change.diff_coverage[0].diff.path) == "field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "old_value"
    assert bundle_change.diff_coverage[0].diff.new == "new_value"


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
