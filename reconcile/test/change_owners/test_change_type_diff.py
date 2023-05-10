import jsonpath_ng
import jsonpath_ng.ext
import pytest

from reconcile.change_owners.change_types import DiffCoverage
from reconcile.change_owners.diff import (
    Diff,
    DiffType,
    deepdiff_path_to_jsonpath,
)
from reconcile.test.change_owners.fixtures import (
    build_bundle_datafile_change,
    build_bundle_resourcefile_change,
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
def test_deepdiff_path_to_jsonpath(
    deep_diff_path: str, expected_json_path: str
) -> None:
    assert str(deepdiff_path_to_jsonpath(deep_diff_path)) == expected_json_path


def test_deepdiff_invalid() -> None:
    with pytest.raises(ValueError):
        deepdiff_path_to_jsonpath("something_invalid")


def test_deepdiff_path_element_with_dot() -> None:
    assert (
        str(deepdiff_path_to_jsonpath("root['data']['main.yaml']"))
        == "data.'main.yaml'"
    )


#
# bundle changes diff detection
#


def test_bundle_change_diff_value_changed() -> None:
    """
    detect a change on a top level field
    """
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="schema",
        old_content={"field": "old_value"},
        new_content={"field": "new_value"},
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "old_value"
    assert bundle_change.diff_coverage[0].diff.new == "new_value"


def test_bundle_change_diff_value_changed_deep() -> None:
    """
    detect a change deeper in the object tree
    """
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="schema",
        old_content={"parent": {"children": [{"age": 1}]}},
        new_content={"parent": {"children": [{"age": 2}]}},
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "parent.children.[0].age"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == 1
    assert bundle_change.diff_coverage[0].diff.new == 2


def test_bundle_change_diff_value_changed_multiple_in_iterable() -> None:
    """
    this testscenario shows how changes can be detected in a list,
    when objects with identifiers and objects without are mixed and shuffled
    """
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        old_content={
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
        new_content={
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


def test_bundle_change_diff_property_added() -> None:
    """
    this test scenario show how a newly added property is correctly
    detected if the containing object has a clear identity.
    """
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        old_content={
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
        new_content={
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


def test_bundle_change_diff_property_removed() -> None:
    """
    this test scenario show how a removed property is correctly
    detected if the containing object has a clear identity.
    """
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        old_content={
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
        new_content={
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


def test_bundle_change_diff_item_added() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        old_content={
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
        new_content={
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


def test_bundle_change_diff_item_removed() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/openshift/namespace-1.yml",
        old_content={
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
        new_content={
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


def test_bundle_change_diff_item_replaced() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/access/user-1.yml",
        old_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "an_item"},
                {"$ref": "old_item"},
                {"$ref": "another_item"},
            ],
        },
        new_content={
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


def test_bundle_change_diff_ref_item_multiple_consecutive_replaced() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/access/user-1.yml",
        old_content={
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
        new_content={
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


def test_bundle_change_diff_ref_item_multiple_replaced() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/access/user-1.yml",
        old_content={
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
        new_content={
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


def test_bundle_change_diff_item_reorder() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/access/user-1.yml",
        old_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "an_item"},
                {"$ref": "reorder_item"},
                {"$ref": "another_item"},
            ],
        },
        new_content={
            "$schema": "/access/user-1.yml",
            "roles": [
                {"$ref": "an_item"},
                {"$ref": "another_item"},
                {"$ref": "reorder_item"},
            ],
        },
    )

    # there is a bundle change ...
    assert bundle_change
    # ... but it has no diffs ...
    assert not bundle_change.diffs
    # ... but it has different SHAs
    assert bundle_change.old_content_sha != bundle_change.new_content_sha


def test_bundle_change_diff_resourcefile_without_schema_unparsable() -> None:
    bundle_change = build_bundle_resourcefile_change(
        path="path",
        schema=None,
        old_content="something_old",
        new_content="something_new",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "something_old"
    assert bundle_change.diff_coverage[0].diff.new == "something_new"


def test_bundle_change_diff_resourcefile_without_schema_parsable() -> None:
    bundle_change = build_bundle_resourcefile_change(
        path="path",
        schema=None,
        old_content="field: old_value",
        new_content="field: new_value",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert bundle_change.old == {"field": "old_value"}
    assert bundle_change.new == {"field": "new_value"}
    assert str(bundle_change.diff_coverage[0].diff.path) == "field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "old_value"
    assert bundle_change.diff_coverage[0].diff.new == "new_value"


def test_bundle_change_diff_resourcefile_with_schema() -> None:
    bundle_change = build_bundle_resourcefile_change(
        path="path",
        schema="schema",
        old_content="""
        field: old_value
        """,
        new_content="""
        field: new_value
        """,
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "old_value"
    assert bundle_change.diff_coverage[0].diff.new == "new_value"


def test_bundle_change_diff_resourcefile_with_schema_unparsable() -> None:
    bundle_change = build_bundle_resourcefile_change(
        path="path",
        schema="schema",
        old_content="somethingsomething",
        new_content="somethingsomething_different",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.CHANGED
    assert bundle_change.diff_coverage[0].diff.old == "somethingsomething"
    assert bundle_change.diff_coverage[0].diff.new == "somethingsomething_different"


def test_bundle_change_resource_file_added() -> None:
    bundle_change = build_bundle_resourcefile_change(
        path="path",
        schema="schema",
        old_content=None,
        new_content="new content",
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.ADDED
    assert bundle_change.diff_coverage[0].diff.old is None
    assert bundle_change.diff_coverage[0].diff.new == "new content"


def test_bundle_change_resource_file_removed() -> None:
    bundle_change = build_bundle_resourcefile_change(
        path="path",
        schema="schema",
        old_content="old content",
        new_content=None,
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.REMOVED
    assert bundle_change.diff_coverage[0].diff.old == "old content"
    assert bundle_change.diff_coverage[0].diff.new is None


def test_bundle_change_resource_file_dict_value_added() -> None:
    bundle_change = build_bundle_resourcefile_change(
        path="path",
        schema="schema",
        old_content='{"field": {}}',
        new_content='{"field": {"new_field": "new_value"}}',
    )

    assert bundle_change
    assert len(bundle_change.diff_coverage) == 1
    assert str(bundle_change.diff_coverage[0].diff.path) == "field.new_field"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.ADDED
    assert bundle_change.diff_coverage[0].diff.old is None
    assert bundle_change.diff_coverage[0].diff.new == "new_value"
