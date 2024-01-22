import pytest
from pytest_mock import MockerFixture

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.bundle import BundleFileType, FileRef
from reconcile.change_owners.change_owners import is_change_admitted
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    DiffCoverage,
)
from reconcile.change_owners.changes import BundleFileChange
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import (
    change_type_to_processor,
)


@pytest.fixture
def restrictive_change(
    restrictive_type: ChangeTypeV1, mocker: MockerFixture
) -> list[BundleFileChange]:
    b = mocker.patch("reconcile.change_owners.changes.BundleFileChange")
    b.diff_coverage = [
        DiffCoverage(
            diff=mocker.patch("reconcile.change_owners.diff.Diff"),
            coverage=[
                ChangeTypeContext(
                    change_type_processor=change_type_to_processor(restrictive_type),
                    context="",
                    origin="",
                    context_file=FileRef(
                        file_type=BundleFileType.DATAFILE,
                        path="/somepath.yml",
                        schema=None,
                    ),
                    approvers=[Approver(org_username="foo")],
                )
            ],
        )
    ]

    return [b]


@pytest.mark.parametrize(("user", "expected"), [("foo", True), ("baz", False)])
def test_assert_restrictive(
    restrictive_change: list[BundleFileChange], user: str, expected: bool
) -> None:
    assert is_change_admitted(restrictive_change, user, {""}) == expected


def test_assert_restrictive_non_restrictive(
    restrictive_type: ChangeTypeV1, mocker: MockerFixture
) -> None:
    b = mocker.patch("reconcile.change_owners.changes.BundleFileChange")
    restrictive_type.restrictive = False
    b.diff_coverage = [
        DiffCoverage(
            diff=mocker.patch("reconcile.change_owners.diff.Diff"),
            coverage=[
                ChangeTypeContext(
                    change_type_processor=change_type_to_processor(restrictive_type),
                    context="",
                    origin="",
                    context_file=FileRef(
                        file_type=BundleFileType.DATAFILE,
                        path="/somepath.yml",
                        schema=None,
                    ),
                    approvers=[Approver(org_username="foo")],
                )
            ],
        )
    ]
    changes = [b]

    assert is_change_admitted(changes, "baz", {""})


def test_assert_restrictive_all_need_approval(
    restrictive_type: ChangeTypeV1, mocker: MockerFixture
) -> None:
    b = mocker.patch("reconcile.change_owners.changes.BundleFileChange")
    restrictive_type_two = restrictive_type.copy()
    restrictive_type_two.name = "restrictive_type_two"
    b.diff_coverage = [
        DiffCoverage(
            diff=mocker.patch("reconcile.change_owners.diff.Diff"),
            coverage=[
                ChangeTypeContext(
                    change_type_processor=change_type_to_processor(restrictive_type),
                    context="",
                    origin=restrictive_type.name,
                    context_file=FileRef(
                        file_type=BundleFileType.DATAFILE,
                        path="/somepath.yml",
                        schema=None,
                    ),
                    approvers=[Approver(org_username="foo")],
                )
            ],
        ),
        DiffCoverage(
            diff=mocker.patch("reconcile.change_owners.diff.Diff"),
            coverage=[
                ChangeTypeContext(
                    change_type_processor=change_type_to_processor(
                        restrictive_type_two
                    ),
                    context="",
                    origin=restrictive_type_two.name,
                    context_file=FileRef(
                        file_type=BundleFileType.DATAFILE,
                        path="/somepath.yml",
                        schema=None,
                    ),
                    approvers=[Approver(org_username="bar")],
                )
            ],
        ),
    ]
    changes = [b]

    assert is_change_admitted(changes, "baz", {"foo", "bar"})
    assert not is_change_admitted(changes, "baz", {"bar"})
    assert is_change_admitted(changes, "foo", {"bar"})


@pytest.mark.parametrize(
    ("good_to_test_approver", "expected"), [({"foo"}, True), ({"baz"}, False)]
)
def test_assert_restrictive_good_to_test(
    restrictive_change: list[BundleFileChange],
    good_to_test_approver: set[str],
    expected: bool,
) -> None:
    assert (
        is_change_admitted(restrictive_change, "baz", good_to_test_approver) == expected
    )
