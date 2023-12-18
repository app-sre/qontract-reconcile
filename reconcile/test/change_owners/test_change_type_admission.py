import pytest
from pytest_mock import MockerFixture

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.bundle import BundleFileType, FileRef
from reconcile.change_owners.change_owners import assert_restrictive
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


def test_assert_restrictive_missing_approver(
    restrictive_change: list[BundleFileChange], mocker: MockerFixture
) -> None:
    exit = mocker.patch("sys.exit")

    assert_restrictive(restrictive_change, "baz", [])
    exit.assert_called_once_with(1)


def test_assert_restrictive_approved(
    restrictive_change: list[BundleFileChange], mocker: MockerFixture
) -> None:
    exit = mocker.patch("sys.exit")
    assert_restrictive(restrictive_change, "foo", [])
    exit.assert_not_called()


def test_assert_restrictive_non_restrictive(
    restrictive_type: ChangeTypeV1, mocker: MockerFixture
) -> None:
    exit = mocker.patch("sys.exit")
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

    assert_restrictive(changes, "baz", [])
    exit.assert_not_called()


def test_assert_restrictive_good_to_test(
    restrictive_change: list[BundleFileChange], mocker: MockerFixture
) -> None:
    exit = mocker.patch("sys.exit")
    assert_restrictive(restrictive_change, "baz", [{"username": "foo"}])

    exit.assert_not_called()


def test_assert_restrictive_not_good_to_test(
    restrictive_change: list[BundleFileChange], mocker: MockerFixture
) -> None:
    exit = mocker.patch("sys.exit")
    assert_restrictive(restrictive_change, "baz", [{"username": "baz"}])

    exit.assert_called_once_with(1)
