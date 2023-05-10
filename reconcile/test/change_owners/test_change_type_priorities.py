from unittest.mock import MagicMock

from reconcile.change_owners.change_types import ChangeTypePriority
from reconcile.change_owners.changes import (
    BundleFileChange,
    get_priority_for_changes,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import change_type_to_processor

#
# priority tests
#


def test_priority_for_changes(
    saas_file_changetype: ChangeTypeV1, secret_promoter_change_type: ChangeTypeV1
):
    saas_file_changetype.priority = ChangeTypePriority.HIGH.value
    secret_promoter_change_type.priority = ChangeTypePriority.MEDIUM.value
    c1 = BundleFileChange(
        fileref=None,  # type: ignore
        old=None,
        new=None,
        diffs=[],
    )
    c1.involved_change_types = MagicMock(  # type: ignore
        return_value=[change_type_to_processor(saas_file_changetype)]
    )
    c2 = BundleFileChange(
        fileref=None,  # type: ignore
        old=None,
        new=None,
        diffs=[],
    )
    c2.involved_change_types = MagicMock(  # type: ignore
        return_value=[change_type_to_processor(secret_promoter_change_type)]
    )

    assert ChangeTypePriority.MEDIUM == get_priority_for_changes([c1, c2])


def test_priorty_for_changes_no_coverage():
    changes = [
        BundleFileChange(
            fileref=None,  # type: ignore
            old=None,
            new=None,
            diffs=[],
        )
    ]
    assert get_priority_for_changes(changes) is None
