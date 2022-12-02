from reconcile.change_owners.change_types import (
    BundleFileChange,
    ChangeTypeContext,
    ChangeTypePriority,
    DiffCoverage,
    build_change_type_processor,
    get_priority_for_changes,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1

pytest_plugins = [
    "reconcile.test.change_owners.fixtures",
]

#
# priority tests
#


def test_priority_for_changes(
    saas_file_changetype: ChangeTypeV1, secret_promoter_change_type: ChangeTypeV1
):
    saas_file_changetype.priority = ChangeTypePriority.HIGH.value
    secret_promoter_change_type.priority = ChangeTypePriority.MEDIUM.value
    changes = [
        BundleFileChange(
            fileref=None,  # type: ignore
            old=None,
            new=None,
            diff_coverage=[
                DiffCoverage(
                    diff=None,  # type: ignore
                    coverage=[
                        ChangeTypeContext(
                            change_type_processor=build_change_type_processor(ct),
                            context="RoleV1 - some-role",
                            approvers=[],
                            context_file=None,  # type: ignore
                        ),
                    ],
                )
            ],
        )
        for ct in [saas_file_changetype, secret_promoter_change_type]
    ]
    assert ChangeTypePriority.MEDIUM == get_priority_for_changes(changes)


def test_priorty_for_changes_no_coverage():
    changes = [
        BundleFileChange(
            fileref=None,  # type: ignore
            old=None,
            new=None,
            diff_coverage=[],
        )
    ]
    assert get_priority_for_changes(changes) is None
