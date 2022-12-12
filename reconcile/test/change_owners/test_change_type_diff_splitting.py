from reconcile.change_owners.change_types import (
    BundleFileType,
    ChangeTypeContext,
    ChangeTypeProcessor,
    FileRef,
    build_change_type_processor,
    create_bundle_file_change,
)
from reconcile.change_owners.diff import DiffType
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import build_jsonpath_change


def build_change_type(name: str, change_selectors: list[str]) -> ChangeTypeProcessor:
    return build_change_type_processor(
        ChangeTypeV1(
            name=name,
            description=name,
            contextType=BundleFileType.DATAFILE.value,
            contextSchema=None,
            changes=[
                build_jsonpath_change(
                    schema=None,
                    selectors=change_selectors,
                )
            ],
            disabled=False,
            priority="urgent",
            inherit=[],
        )
    )


def test_root_diff_fully_covered_by_splits():
    bundle_change = create_bundle_file_change(
        path="path",
        schema=None,
        file_type=BundleFileType.DATAFILE,
        old_file_content=None,
        new_file_content={"split-a": "a", "split-b": "b"},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1
    assert bundle_change.diff_coverage[0].diff.path_str() == "$"
    assert bundle_change.diff_coverage[0].diff.diff_type == DiffType.ADDED

    split_a = ChangeTypeContext(
        change_type_processor=build_change_type("split-a", ["split-a"]),
        context="context",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    split_b = ChangeTypeContext(
        change_type_processor=build_change_type("split-b", ["split-b"]),
        context="context",
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


def test_root_diff_uncovered_fully_covered_by_splits():
    bundle_change = create_bundle_file_change(
        path="path",
        schema=None,
        file_type=BundleFileType.DATAFILE,
        old_file_content=None,
        new_file_content={"split-a": "a", "split-b": "b"},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    split_a = ChangeTypeContext(
        change_type_processor=build_change_type("split-a", ["split-a"]),
        context="context",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    split_b = ChangeTypeContext(
        change_type_processor=build_change_type("split-b", ["split-b"]),
        context="context",
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


def test_root_diff_uncovered():
    bundle_change = create_bundle_file_change(
        path="path",
        schema=None,
        file_type=BundleFileType.DATAFILE,
        old_file_content=None,
        new_file_content={"split-a": "a", "split-b": "b", "split-c": "c"},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    split_a = ChangeTypeContext(
        change_type_processor=build_change_type("split-a", ["split-a"]),
        context="context",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    split_b = ChangeTypeContext(
        change_type_processor=build_change_type("split-b", ["split-b"]),
        context="context",
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


def test_nested_splits():
    bundle_change = create_bundle_file_change(
        path="path",
        schema=None,
        file_type=BundleFileType.DATAFILE,
        old_file_content=None,
        new_file_content={"top": {"sub": {"sub-sub": "value"}}},
    )

    assert bundle_change
    # only the root diff is present
    assert len(bundle_change.diff_coverage) == 1

    top = ChangeTypeContext(
        change_type_processor=build_change_type("top", ["top"]),
        context="context",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    sub = ChangeTypeContext(
        change_type_processor=build_change_type("sub", ["top.sub"]),
        context="context",
        context_file=FileRef(
            path="context_file.yml", file_type=BundleFileType.DATAFILE, schema=None
        ),
        approvers=[],
    )

    sub_sub = ChangeTypeContext(
        change_type_processor=build_change_type("sub-sub", ["top.sub.sub-sub"]),
        context="context",
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
