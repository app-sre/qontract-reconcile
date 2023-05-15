import pytest

from reconcile.change_owners.bundle import (
    DATAFILE_PATH_FIELD_NAME,
    DATAFILE_SCHEMA_FIELD_NAME,
    DATAFILE_SHA256SUM_FIELD_NAME,
    BundleFileType,
    QontractServerDatafileDiff,
    QontractServerDiff,
    QontractServerResourcefileDiff,
    QontractServerResourcefileDiffState,
)
from reconcile.change_owners.changes import (
    aggregate_file_moves,
    parse_bundle_changes,
)
from reconcile.test.change_owners.fixtures import (
    QontractServerBundleDiffDataBuilder,
    build_bundle_datafile_change,
    build_test_datafile,
)

#
# bundle file change parsing
#


@pytest.fixture
def qontract_server_diff() -> QontractServerDiff:
    return (
        QontractServerBundleDiffDataBuilder()
        .add_datafile(
            path="/my/datafile.yml",
            schema="/my/schema.yml",
            old_content={"foo": "bar"},
            new_content={"foo": "baz"},
        )
        .add_resource_file(
            path="/my/resource.yml",
            old_content="old content",
            new_content="new content",
        )
        .diff
    )


def test_parse_bundle_changes(qontract_server_diff: QontractServerDiff) -> None:
    parsed_bundle_changes = parse_bundle_changes(qontract_server_diff)
    assert len(parsed_bundle_changes) == 2

    datafile_change = next(
        (
            bc
            for bc in parsed_bundle_changes
            if bc.fileref.file_type == BundleFileType.DATAFILE
        ),
        None,
    )
    assert datafile_change
    assert datafile_change.fileref.path == "/my/datafile.yml"
    assert datafile_change.fileref.schema == "/my/schema.yml"
    assert datafile_change.old_content_sha
    assert datafile_change.new_content_sha
    assert datafile_change.old_content_sha != datafile_change.new_content_sha
    assert not datafile_change.metadata_only_change

    # check that metadata fields are not present in the content
    assert datafile_change.old == {"foo": "bar"}
    assert datafile_change.new == {"foo": "baz"}

    resourcefile_change = next(
        (
            bc
            for bc in parsed_bundle_changes
            if bc.fileref.file_type == BundleFileType.RESOURCEFILE
        ),
        None,
    )
    assert resourcefile_change
    assert resourcefile_change.fileref.path == "/my/resource.yml"
    assert resourcefile_change.fileref.schema is None
    assert resourcefile_change.old_content_sha
    assert resourcefile_change.new_content_sha
    assert resourcefile_change.old_content_sha != resourcefile_change.new_content_sha
    assert not resourcefile_change.metadata_only_change


def test_parse_bundle_changes_skip_datafiles_with_no_changes() -> None:
    data_diff = (
        QontractServerBundleDiffDataBuilder()
        .add_datafile(
            path="/my/datafile.yml",
            schema="/my/schema.yml",
            old_content={"foo": "bar"},
            new_content={"foo": "bar"},
        )
        .diff
    )

    parsed_bundle_changes = parse_bundle_changes(data_diff)
    assert len(parsed_bundle_changes) == 0


def test_parse_bundle_changes_skip_resources_with_no_changes() -> None:
    data_diff = (
        QontractServerBundleDiffDataBuilder()
        .add_resource_file(
            path="/my/resource.yml",
            old_content="content",
            new_content="content",
        )
        .diff
    )
    parsed_bundle_changes = parse_bundle_changes(data_diff)
    assert len(parsed_bundle_changes) == 0


def test_parse_bundle_changes_only_checksum_changed() -> None:
    """
    Only the checksum changed. This is still a BundleFileChange but only
    a metadata one without diffs.
    """
    data_diff = (
        QontractServerBundleDiffDataBuilder()
        .add_datafile(
            path="/my/resource.yml",
            schema="/my/schema.yml",
            old_content={"foo": "bar"},
            new_content={"foo": "bar"},
            old_sha_override="old_sha",
            new_sha_override="new_sha",
        )
        .diff
    )
    parsed_bundle_changes = parse_bundle_changes(data_diff)
    assert len(parsed_bundle_changes) == 1
    bundle_change = parsed_bundle_changes[0]

    # no diffs are present
    assert not bundle_change.diffs
    assert not bundle_change.diff_coverage

    # but the sha changed and the it is marked as metadata only change
    assert bundle_change.old_content_sha != bundle_change.new_content_sha
    assert bundle_change.metadata_only_change


#
# qontract server datafile diff endpoint dataclasses
#


@pytest.fixture
def datafile_diff() -> QontractServerDatafileDiff:
    return QontractServerDatafileDiff(
        datafilepath="/my/datafile.yml",
        datafileschema="/my/schema.yml",
        old={
            "foo": "bar",
            DATAFILE_SHA256SUM_FIELD_NAME: "old_sha",
            DATAFILE_PATH_FIELD_NAME: "/old/datafile.yml",
            DATAFILE_SCHEMA_FIELD_NAME: "/my/schema.yml",
        },
        new={
            "foo": "baz",
            DATAFILE_SHA256SUM_FIELD_NAME: "new_sha",
            DATAFILE_PATH_FIELD_NAME: "/new/datafile.yml",
            DATAFILE_SCHEMA_FIELD_NAME: "/my/schema.yml",
        },
    )


def test_qontract_server_datafile_diff_sha_access(
    datafile_diff: QontractServerDatafileDiff,
) -> None:
    """
    Test that the SHA is extracted properly from the datafile content.
    """
    assert datafile_diff.old_data_sha == "old_sha"
    datafile_diff.old = {}
    assert datafile_diff.old_data_sha is None
    datafile_diff.old = None
    assert datafile_diff.old_data_sha is None

    assert datafile_diff.new_data_sha == "new_sha"
    datafile_diff.new = {}
    assert datafile_diff.new_data_sha is None
    datafile_diff.new = None
    assert datafile_diff.new_data_sha is None


def test_qontract_server_datafile_diff_path_access(
    datafile_diff: QontractServerDatafileDiff,
) -> None:
    """
    Test that the SHA is extracted properly from the datafile content.
    """
    assert datafile_diff.old_datafilepath == "/old/datafile.yml"
    datafile_diff.old = {}
    assert datafile_diff.old_datafilepath is None
    datafile_diff.old = None
    assert datafile_diff.old_datafilepath is None

    assert datafile_diff.new_datafilepath == "/new/datafile.yml"
    datafile_diff.new = {}
    assert datafile_diff.new_datafilepath is None
    datafile_diff.new = None
    assert datafile_diff.new_datafilepath is None


def test_qontract_server_datafile_diff_data_cleanup(
    datafile_diff: QontractServerDatafileDiff,
) -> None:
    """
    Test that the datafile content is cleaned from metadata.
    """
    assert datafile_diff.cleaned_old_data == {"foo": "bar"}
    datafile_diff.old = {}
    assert datafile_diff.cleaned_old_data == {}
    datafile_diff.old = None
    assert datafile_diff.cleaned_old_data is None

    assert datafile_diff.cleaned_new_data == {"foo": "baz"}
    datafile_diff.new = {}
    assert datafile_diff.cleaned_new_data == {}
    datafile_diff.new = None
    assert datafile_diff.cleaned_new_data is None


#
# qontract server resourcefile diff endpoint dataclasses
#


@pytest.fixture
def resourcefile_diff() -> QontractServerResourcefileDiff:
    return QontractServerResourcefileDiff(
        resourcepath="/my/resourcefile.yml",
        old=QontractServerResourcefileDiffState(
            **{
                "path": "/my/resourcefile.yml",
                "content": "old content",
                "$schema": None,
                "sha256sum": "old_sha",
            }
        ),
        new=QontractServerResourcefileDiffState(
            **{
                "path": "/new/resourcefile.yml",
                "content": "new content",
                "$schema": None,
                "sha256sum": "new_sha",
            }
        ),
    )


def test_qontract_server_resourcefile_diff_schema_access(
    resourcefile_diff: QontractServerResourcefileDiff,
) -> None:
    """
    Test that the schema is extracted properly from the resourcefile content.
    """
    assert resourcefile_diff.resourcefileschema is None

    assert resourcefile_diff.old
    resourcefile_diff.old.resourcefileschema = "/my/schema.yml"
    assert resourcefile_diff.resourcefileschema == "/my/schema.yml"

    assert resourcefile_diff.new
    resourcefile_diff.new.resourcefileschema = "/my/new-schema.yml"
    assert resourcefile_diff.resourcefileschema == "/my/new-schema.yml"


#
# post processing - aggregate file moves
#


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
    result = aggregate_file_moves(list(file.file_move("/new/path.yml")))
    assert len(result) == 1
    file_change = result[0]
    # no diffs... the file was just moved
    assert len(file_change.diffs) == 0


def test_aggregate_file_moves_mixed() -> None:
    """
    This test covers the case where a regular file change and a file move happen
    in the same MR.
    """
    # move a file
    changes = list(
        build_test_datafile(
            filepath="/old/path.yml",
            content={"foo": "bar"},
            schema="/my/schema.yml",
        ).file_move("/new/path.yml")
    )
    # add a regular change
    changes.append(
        build_test_datafile(
            filepath="/another/path.yml",
            content={"hey": "ho"},
            schema="/my/schema.yml",
        ).create_bundle_change({"hey": "you"})
    )
    result = aggregate_file_moves(changes)
    assert len(result) == 2


#
# content with metadata
#


def test_get_new_content_with_metadata() -> None:
    path = "/my/path.yml"
    schema = "/my/schema.yml"
    bc = build_bundle_datafile_change(
        path=path,
        schema=schema,
        old_content=None,
        new_content={
            "field": "new",
        },
    )
    assert bc

    assert bc.old_content_with_metadata is None

    assert bc.new_content_with_metadata == {
        "path": path,
        "$schema": schema,
        "field": "new",
    }


def test_get_old_content_with_metadata() -> None:
    path = "/my/path.yml"
    schema = "/my/schema.yml"
    bc = build_bundle_datafile_change(
        path=path,
        schema=schema,
        old_content={
            "field": "old",
        },
        new_content=None,
    )
    assert bc

    assert bc.old_content_with_metadata == {
        "path": path,
        "$schema": schema,
        "field": "old",
    }

    assert bc.new_content_with_metadata is None
