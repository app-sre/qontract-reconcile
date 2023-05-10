import jsonpath_ng

from reconcile.change_owners.bundle import (
    BundleFileType,
    FileRef,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    DiffCoverage,
)
from reconcile.change_owners.diff import (
    Diff,
    DiffType,
)
from reconcile.test.change_owners.fixtures import (
    build_bundle_datafile_change,
    build_change_type,
)


def test_root_diff_fully_covered_by_splits() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/my/schema-1.yml",
        old_content=None,
        new_content={"split-a": "a", "split-b": "b"},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1
    assert bundle_change.diff_coverage[0].diff.path_str() == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.ADDED

    split_a = ChangeTypeContext(
        change_type_processor=build_change_type("split-a", ["split-a"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    split_b = ChangeTypeContext(
        change_type_processor=build_change_type("split-b", ["split-b"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    bundle_change.cover_changes(split_a)
    bundle_change.cover_changes(split_b)
    # after consolidation, the root diff is gone and only two splits are present
    diffs = bundle_change.diff_coverage
    assert len(diffs) == 2

    for d in diffs:
        assert d.is_covered()


def test_root_diff_uncovered_fully_covered_by_splits() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/my/schema-1.yml",
        old_content=None,
        new_content={"split-a": "a", "split-b": "b"},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    split_a = ChangeTypeContext(
        change_type_processor=build_change_type("split-a", ["split-a"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    split_b = ChangeTypeContext(
        change_type_processor=build_change_type("split-b", ["split-b"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    bundle_change.cover_changes(split_a)
    bundle_change.cover_changes(split_b)

    # after consolidation, the root diff is gone and only two splits are present
    diffs = bundle_change.diff_coverage
    assert len(diffs) == 2

    for d in diffs:
        assert d.is_covered()


def test_root_diff_uncovered() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/my/schema-1.yml",
        old_content=None,
        new_content={"split-a": "a", "split-b": "b", "split-c": "c"},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    split_a = ChangeTypeContext(
        change_type_processor=build_change_type("split-a", ["split-a"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    split_b = ChangeTypeContext(
        change_type_processor=build_change_type("split-b", ["split-b"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    bundle_change.cover_changes(split_a)
    bundle_change.cover_changes(split_b)

    diffs = {d.diff.path_str(): d for d in bundle_change.diff_coverage}
    # the root split is not covered in full by the other change-types
    # so it must remain, next to the two splits
    assert len(diffs) == 3

    # the root diff remains uncovered (directly and indirectly)
    assert not diffs["$"].is_directly_covered()
    assert not diffs["$"].is_covered_by_splits()
    assert not diffs["$"].is_covered()
    assert {"split-a", "split-b"} == {s.diff.path_str() for s in diffs["$"]._split_into}

    assert diffs["split-a"].is_covered()
    assert diffs["split-b"].is_covered()


def test_nested_splits() -> None:
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/my/schema-1.yml",
        old_content=None,
        new_content={"top": {"sub": {"sub-sub": "value"}}},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    top = ChangeTypeContext(
        change_type_processor=build_change_type("top", ["top"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    sub = ChangeTypeContext(
        change_type_processor=build_change_type("sub", ["top.sub"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    sub_sub = ChangeTypeContext(
        change_type_processor=build_change_type("sub-sub", ["top.sub.sub-sub"]),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    # call the coverage function in this order is on purpose

    # so that the split functionality must reconsolidate the diff split tree
    # first add a split for top.sub.sub-sub
    bundle_change.cover_changes(sub_sub)
    # then add a split for root, which means that top.sub.sub-sub needs to be
    # placed under the split for top
    bundle_change.cover_changes(top)
    # then add the split for top.sub that goes between the top and top.sub.sub-sub
    # split within the split tree
    bundle_change.cover_changes(sub)

    diffs = {d.diff.path_str(): d for d in bundle_change.diff_coverage}

    # check that the `top` field has a split for `top.sub` and is covered
    # by the `top` change-type
    assert ["top.sub"] == [s.diff.path_str() for s in diffs["top"]._split_into]
    assert diffs["top"].is_directly_covered()
    assert {ctx.change_type_processor.name for ctx in diffs["top"].coverage} == {
        top.change_type_processor.name
    }

    # check that the `top.sub` field has a split for `top.sub.sub-sub` and is covered
    # by the `sub` and `top` change-types
    assert ["top.sub.sub-sub"] == [
        s.diff.path_str() for s in diffs["top.sub"]._split_into
    ]
    assert diffs["top.sub"].is_directly_covered()
    assert {ctx.change_type_processor.name for ctx in diffs["top.sub"].coverage} == {
        top.change_type_processor.name,
        sub.change_type_processor.name,
    }

    # check that the `top.sub.sub-sub` field is not split and is covered
    # by the `sub-sub`, `sub` and `top` change-types
    assert [] == [s.diff.path_str() for s in diffs["top.sub.sub-sub"]._split_into]
    assert diffs["top.sub.sub-sub"].is_directly_covered()
    assert not diffs["top.sub.sub-sub"].is_covered_by_splits()
    assert {
        ctx.change_type_processor.name for ctx in diffs["top.sub.sub-sub"].coverage
    } == {
        top.change_type_processor.name,
        sub.change_type_processor.name,
        sub_sub.change_type_processor.name,
    }


def test_diff_splitting_empty_parent_coverage() -> None:
    """
    If splits cover all fields or list elements of a parent diff, the parent diff
    is considered covered, even if there is not explicit coverage on the parent element
    ifself.
    """

    schema = "/my/schema-1.yml"
    bundle_change = build_bundle_datafile_change(
        path="path",
        schema=schema,
        old_content=None,
        new_content={"roles": ["role1", "role2"]},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    # this change-type only coveres entries of the `roles` list but not the list itself
    role_change_type = ChangeTypeContext(
        change_type_processor=build_change_type(
            name="roles",
            change_selectors=["roles[*]"],
            change_schema=schema,
        ),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml",
            file_type=BundleFileType.DATAFILE,
            schema=schema,
        ),
        approvers=[],
    )
    bundle_change.cover_changes(role_change_type)

    diffs = {d.diff.path_str(): d for d in bundle_change.diff_coverage}
    assert len(diffs) == 2
    assert diffs["roles.[0]"].is_directly_covered()
    assert diffs["roles.[1]"].is_directly_covered()


def test_nested_diff_splitting_empty_parent_coverage() -> None:
    """
    Same as test_diff_splitting_empty_parent_coverage but with a diff that is nested deeper
    """

    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/my/schema-1.yml",
        old_content={
            "top": {
                "middle": {
                    "some": "value",
                },
            }
        },
        new_content={
            "top": {
                "middle": {
                    "some": "value",
                    "self_serviceable": {
                        "a": "a",
                        "b": "b",
                    },
                }
            }
        },
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    # this change-type only coveres the elements a and b of the the self_serviceable
    # object but not the object itself
    role_change_type = ChangeTypeContext(
        change_type_processor=build_change_type(
            "self_serviceable",
            ["top.middle.self_serviceable.a", "top.middle.self_serviceable.b"],
        ),
        context="context",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )
    bundle_change.cover_changes(role_change_type)

    diffs = {d.diff.path_str(): d for d in bundle_change.diff_coverage}
    assert len(diffs) == 2
    assert diffs["top.middle.self_serviceable.a"].is_directly_covered()
    assert diffs["top.middle.self_serviceable.b"].is_directly_covered()


def test_diff_splitting_two_contexts_on_same_split() -> None:
    """
    Test that a split can be covered by multiple contexts.
    """

    bundle_change = build_bundle_datafile_change(
        path="path",
        schema="/my/schema-1.yml",
        old_content=None,
        new_content={"something": "else", "roles": ["role"]},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    # this change-type only coveres entries of the `roles` list but not the list itself
    ctx_1 = ChangeTypeContext(
        change_type_processor=build_change_type("roles", ["roles[*]"]),
        context="context-1",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )
    ctx_2 = ChangeTypeContext(
        change_type_processor=build_change_type("roles", ["roles[*]"]),
        context="context-2",
        origin="",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )
    bundle_change.cover_changes(ctx_1)
    bundle_change.cover_changes(ctx_2)

    diffs = {d.diff.path_str(): d for d in bundle_change.diff_coverage}
    assert "roles.[0]" in diffs
    assert {c.context for c in diffs["roles.[0]"].coverage} == {
        ctx_1.context,
        ctx_2.context,
    }


#
# D I F F  C O V E R A G E   U T I L I T I E S
#


def test_diff_coverage_path_under_root_changed_path() -> None:
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("$"), new=None, old=None
        ),
        coverage=[],
    )

    assert dc.path_under_changed_path(jsonpath_ng.parse("some.path"))


def test_diff_coverage_path_under_changed_path() -> None:
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("path"), new=None, old=None
        ),
        coverage=[],
    )

    assert dc.path_under_changed_path(jsonpath_ng.parse("path.subpath"))


def test_diff_coverage_path_not_under_changed_path() -> None:
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("path"), new=None, old=None
        ),
        coverage=[],
    )

    assert not dc.path_under_changed_path(jsonpath_ng.parse("anotherpath"))


def test_diff_coverage_path_is_changed_path() -> None:
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("path"), new=None, old=None
        ),
        coverage=[],
    )

    assert not dc.path_under_changed_path(jsonpath_ng.parse("path"))
