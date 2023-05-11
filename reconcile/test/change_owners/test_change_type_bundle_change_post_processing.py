import pytest

from reconcile.change_owners.changes import (
    InvalidBundleFileMetadataError,
    aggregate_file_moves,
)
from reconcile.change_owners.diff import (
    PATH_FIELD_NAME,
    SHA256SUM_FIELD_NAME,
    DiffType,
)
from reconcile.test.change_owners.fixtures import build_test_datafile


def test_aggregate_file_moves() -> None:
    """
    This test only moves the file and does not change the content.
    Therefore the result is a single change.
    """
    file = build_test_datafile(
        filepath="/old/path.yml",
        content={"foo": "bar"},
        schema="/my/schema.yml",
    )
    result = aggregate_file_moves(list(file.move("/new/path.yml")))
    assert len(result) == 1
    file_change = result[0]
    assert len(file_change.diffs) == 1
    diff = file_change.diffs[0]
    assert diff.path_str() == PATH_FIELD_NAME


def test_aggregate_file_moves_additional_changes() -> None:
    """
    This test does not only move the file but changes a field as well.
    Therefore it is not a pure move anymore and the result are the regular two
    detected changes.
    """
    file = build_test_datafile(
        filepath="/old/path.yml",
        content={"foo": "bar"},
        schema="/my/schema.yml",
    )
    result = aggregate_file_moves(list(file.move("/new/path.yml", {"foo": "baz"})))
    assert len(result) == 2
    for c in result:
        if c.fileref.path == "/old/path.yml":
            assert (
                c.diffs[0].path_str() == "$"
                and c.diffs[0].diff_type == DiffType.REMOVED
            )
        elif c.fileref.path == "/new/path.yml":
            assert (
                c.diffs[0].path_str() == "$" and c.diffs[0].diff_type == DiffType.ADDED
            )
        else:
            pytest.fail("Unexpected change")


def test_aggregate_file_moves_mixed() -> None:
    """
    This test covers the case where a regular file change and a file move happen
    in the same MR.
    """
    changes = list(
        build_test_datafile(
            filepath="/old/path.yml",
            content={"foo": "bar"},
            schema="/my/schema.yml",
        ).move("/new/path.yml")
    )
    changes.append(
        build_test_datafile(
            filepath="/another/path.yml",
            content={"hey": "ho"},
            schema="/my/schema.yml",
        ).create_bundle_change({"hey": "you"})
    )
    result = aggregate_file_moves(changes)
    assert len(result) == 2
    for c in result:
        if c.fileref.path == "/old/path.yml":
            assert (
                c.diffs[0].path_str() == PATH_FIELD_NAME
                and c.diffs[0].diff_type == DiffType.CHANGED
            )
        elif c.fileref.path == "/another/path.yml":
            assert (
                c.diffs[0].path_str() == "hey"
                and c.diffs[0].diff_type == DiffType.CHANGED
            )
        else:
            pytest.fail("Unexpected change")


def test_aggregate_file_moves_with_metadata_error() -> None:
    """
    Test that an InvalidBundleFileMetadataError prevents the aggregation of
    changes.
    """
    changes = list(
        build_test_datafile(
            filepath="/old/path.yml",
            content={"foo": "bar"},
            schema="/my/schema.yml",
        ).move("/new/path.yml")
    )
    # make the change invalid from a metadata perspective
    for c in changes:
        if c.old:
            del c.old[SHA256SUM_FIELD_NAME]
        if c.new:
            del c.new[SHA256SUM_FIELD_NAME]

    with pytest.raises(InvalidBundleFileMetadataError):
        aggregate_file_moves(changes)
