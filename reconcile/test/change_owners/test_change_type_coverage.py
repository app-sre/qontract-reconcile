import jsonpath_ng
import pytest

from reconcile.change_owners.change_types import (
    Approver,
    ChangeTypeContext,
    DiffCoverage,
)
from reconcile.change_owners.changes import (
    METADATA_CHANGE_PATH,
    aggregate_file_moves,
)
from reconcile.change_owners.diff import (
    Diff,
    DiffType,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import (
    StubFile,
    build_bundle_datafile_change,
    build_test_datafile,
    change_type_to_processor,
)

#
# processing change coverage on a change type context
#


def test_cover_changes_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
) -> None:
    saas_file_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )
    saas_file_change.cover_changes(ctx)

    assert saas_file_change.diff_coverage
    assert saas_file_change.all_changes_covered()
    assert saas_file_change.diff_coverage[0].is_covered()
    assert saas_file_change.diff_coverage[0].coverage == [ctx]


def test_uncovered_change_because_change_type_is_disabled(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
) -> None:
    saas_file_changetype.disabled = True
    saas_file_change = saas_file.create_bundle_change(
        {"resourceTemplates[0].targets[0].ref": "new-ref"}
    )
    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )
    saas_file_change.cover_changes(ctx)

    assert saas_file_change.diff_coverage
    assert not saas_file_change.all_changes_covered()
    for dc in saas_file_change.diff_coverage:
        if not dc.is_covered():
            assert dc.coverage[0].disabled


def test_uncovered_change_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
) -> None:
    saas_file_change = saas_file.create_bundle_change({"name": "new-name"})
    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )
    saas_file_change.cover_changes(ctx)

    assert saas_file_change.diff_coverage
    assert all(not dc.is_covered() for dc in saas_file_change.diff_coverage)


def test_partially_covered_change_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
) -> None:
    ref_update_path = "resourceTemplates.[0].targets.[0].ref"
    saas_file_change = saas_file.create_bundle_change(
        # the ref update is covered by the saas_file change type
        # but the name update is not
        {ref_update_path: "new-ref", "name": "new-name"}
    )
    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    saas_file_change.cover_changes(ctx)
    for coverage in saas_file_change.diff_coverage:
        if coverage.diff.path_str() == "name":
            assert not coverage.is_covered()
        elif coverage.diff.path_str() == ref_update_path:
            assert coverage.is_covered()
            assert coverage.coverage == [ctx]
        else:
            pytest.fail("unexpected changed path")


def test_root_change_type(
    cluster_owner_change_type: ChangeTypeV1, saas_file: StubFile
) -> None:
    namespace_change = build_bundle_datafile_change(
        path="/my/namespace.yml",
        schema="/openshift/namespace-1.yml",
        old_content={
            "cluster": {
                "$ref": "cluster.yml",
            },
            "networkPolicy": [
                {"$ref": "networkpolicy.yml"},
            ],
        },
        new_content={
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
        change_type_processor=change_type_to_processor(cluster_owner_change_type),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    namespace_change.cover_changes(ctx)
    coverage = namespace_change.diff_coverage[0]
    assert coverage.is_covered()


def test_diff_no_coverage() -> None:
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("$"), new=None, old=None
        ),
        coverage=[],
    )
    assert not dc.is_covered()


def test_diff_covered(saas_file_changetype: ChangeTypeV1) -> None:
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("$"), new=None, old=None
        ),
        coverage=[
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                origin="",
                approvers=[],
                context_file=None,  # type: ignore
            ),
        ],
    )
    assert dc.is_covered()


def test_diff_covered_many(
    saas_file_changetype: ChangeTypeV1, role_member_change_type: ChangeTypeV1
) -> None:
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("$"), new=None, old=None
        ),
        coverage=[
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                origin="",
                approvers=[],
                context_file=None,  # type: ignore
            ),
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(role_member_change_type),
                context="RoleV1 - some-role",
                origin="",
                approvers=[],
                context_file=None,  # type: ignore
            ),
        ],
    )
    assert dc.is_covered()


def test_diff_covered_partially_disabled(
    saas_file_changetype: ChangeTypeV1, role_member_change_type: ChangeTypeV1
) -> None:
    role_member_change_type.disabled = True
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("$"), new=None, old=None
        ),
        coverage=[
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                origin="",
                approvers=[],
                context_file=None,  # type: ignore
            ),
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(role_member_change_type),
                context="RoleV1 - some-role",
                origin="",
                approvers=[],
                context_file=None,  # type: ignore
            ),
        ],
    )
    assert dc.is_covered()


def test_diff_no_coverage_all_disabled(
    saas_file_changetype: ChangeTypeV1, role_member_change_type: ChangeTypeV1
) -> None:
    role_member_change_type.disabled = True
    saas_file_changetype.disabled = True
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("$"), new=None, old=None
        ),
        coverage=[
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(saas_file_changetype),
                context="RoleV1 - some-role",
                origin="",
                approvers=[],
                context_file=None,  # type: ignore
            ),
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(role_member_change_type),
                context="RoleV1 - some-role",
                origin="",
                approvers=[],
                context_file=None,  # type: ignore
            ),
        ],
    )
    assert not dc.is_covered()


def test_no_diff_but_sha_change(saas_file_changetype: ChangeTypeV1) -> None:
    # create a file change with no diff but with a SHA change
    saas_file_change = build_bundle_datafile_change(
        path="/my/saas-file.yml",
        schema="/app-sre/saas-file-2.yml",
        old_content={
            "foo": "same",
        },
        new_content={
            "foo": "same",
        },
        old_sha_override="old_sha",
        new_sha_override="new_sha",
    )
    assert saas_file_change
    assert len(saas_file_change.diffs) == 0
    assert saas_file_change.metadata_only_change

    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file_change.fileref,
    )
    saas_file_change.cover_changes(ctx)

    assert len(saas_file_change.diff_coverage) == 1
    dc = saas_file_change.diff_coverage[0]
    assert dc.diff.path_str() == METADATA_CHANGE_PATH
    assert dc.coverage == [ctx]


def test_no_diff_but_file_move(saas_file_changetype: ChangeTypeV1) -> None:
    # create a file change with no diff but one that moved
    moves = aggregate_file_moves(
        list(
            build_test_datafile(
                filepath="/my/saas-file.yml",
                schema="/app-sre/saas-file-2.yml",
                content={
                    "foo": "same",
                },
            ).file_move("/another/path.yml")
        )
    )
    assert len(moves) == 1
    saas_file_move = moves[0]

    assert len(saas_file_move.diffs) == 0
    assert saas_file_move.metadata_only_change

    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file_move.fileref,
    )
    saas_file_move.cover_changes(ctx)

    assert len(saas_file_move.diff_coverage) == 1
    dc = saas_file_move.diff_coverage[0]
    assert dc.diff.path_str() == METADATA_CHANGE_PATH
    assert dc.coverage == [ctx]
