import jsonpath_ng

from reconcile.change_owners.bundle import BundleFileType
from reconcile.change_owners.change_types import (
    Approver,
    ChangeTypeContext,
    DiffCoverage,
)
from reconcile.change_owners.changes import create_bundle_file_change
from reconcile.change_owners.diff import (
    Diff,
    DiffType,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import (
    StubFile,
    change_type_to_processor,
)

#
# processing change coverage on a change type context
#


def test_cover_changes_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
):
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

    assert saas_file_change.all_changes_covered()
    assert saas_file_change.diff_coverage[0].is_covered()
    assert saas_file_change.diff_coverage[0].coverage == [ctx]


def test_uncovered_change_because_change_type_is_disabled(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
):
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
    assert not saas_file_change.all_changes_covered()
    for dc in saas_file_change.diff_coverage:
        if not dc.is_covered():
            assert dc.coverage[0].disabled


def test_uncovered_change_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
):
    saas_file_change = saas_file.create_bundle_change({"name": "new-name"})
    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )
    saas_file_change.cover_changes(ctx)
    assert all(not dc.is_covered() for dc in saas_file_change.diff_coverage)


def test_partially_covered_change_one_file(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
):
    ref_update_path = "resourceTemplates.[0].targets.[0].ref"
    saas_file_change = saas_file.create_bundle_change(
        {ref_update_path: "new-ref", "name": "new-name"}
    )
    ref_update_diff = next(
        d for d in saas_file_change.diff_coverage if str(d.diff.path) == ref_update_path
    )
    ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    covered_diffs = saas_file_change.cover_changes(ctx)
    assert [ref_update_diff.diff] == covered_diffs


def test_root_change_type(cluster_owner_change_type: ChangeTypeV1, saas_file: StubFile):
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
        change_type_processor=change_type_to_processor(cluster_owner_change_type),
        context="RoleV1 - some-role",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    covered_diffs = namespace_change.cover_changes(ctx)
    assert covered_diffs


def test_diff_no_coverage():
    dc = DiffCoverage(
        diff=Diff(
            diff_type=DiffType.ADDED, path=jsonpath_ng.parse("$"), new=None, old=None
        ),
        coverage=[],
    )
    assert not dc.is_covered()


def test_diff_covered(saas_file_changetype: ChangeTypeV1):
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
):
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
):
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
):
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
