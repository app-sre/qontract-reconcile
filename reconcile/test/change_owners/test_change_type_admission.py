from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.bundle import BundleFileType, FileRef
from reconcile.change_owners.change_owners import (
    is_change_admitted,
    is_self_service_portion_approved,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    DiffCoverage,
)
from reconcile.change_owners.decision import ChangeDecision, DecisionCommand
from reconcile.test.change_owners.fixtures import (
    change_type_to_processor,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from reconcile.change_owners.changes import BundleFileChange
    from reconcile.gql_definitions.change_owners.queries.change_types import (
        ChangeTypeV1,
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
    changes = [cast("BundleFileChange", b)]  # the cast is to make mypy happy

    assert is_change_admitted(changes, "baz", {""})


def test_assert_restrictive_all_need_approval(
    restrictive_type: ChangeTypeV1, mocker: MockerFixture
) -> None:
    b = mocker.patch("reconcile.change_owners.changes.BundleFileChange")
    restrictive_type_two = restrictive_type.model_copy()
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
    changes = [cast("BundleFileChange", b)]  # the cast is to make mypy happy

    assert is_change_admitted(changes, "baz", {"foo", "bar"})
    assert not is_change_admitted(changes, "baz", {"bar"})
    assert is_change_admitted(changes, "foo", {"bar"})


@pytest.mark.parametrize(
    ("ok_to_test_approver", "expected"), [({"foo"}, True), ({"baz"}, False)]
)
def test_assert_restrictive_ok_to_test(
    restrictive_change: list[BundleFileChange],
    ok_to_test_approver: set[str],
    expected: bool,
) -> None:
    assert (
        is_change_admitted(restrictive_change, "baz", ok_to_test_approver) == expected
    )


#
# self-service portion approval tests
#


def _change_decision(mocker: MockerFixture, *, covered: bool) -> ChangeDecision:
    return ChangeDecision(
        file=mocker.patch("reconcile.change_owners.bundle.FileRef"),
        diff=mocker.patch("reconcile.change_owners.diff.Diff"),
        coverage=[
            mocker.patch("reconcile.change_owners.change_types.ChangeTypeContext")
        ]
        if covered
        else [],
    )


def test_self_service_portion_approved_no_covered_changes(
    mocker: MockerFixture,
) -> None:
    """an MR with only non-self-serviceable changes is vacuously approved here"""
    uncovered = _change_decision(mocker, covered=False)
    assert is_self_service_portion_approved([uncovered])


def test_self_service_portion_approved_ignores_uncovered_changes(
    mocker: MockerFixture,
) -> None:
    """the non-self-serviceable part of the MR must not block this check"""
    covered = _change_decision(mocker, covered=True)
    covered.apply_context_decision("ctx", DecisionCommand.APPROVED)
    uncovered = _change_decision(mocker, covered=False)
    assert is_self_service_portion_approved([covered, uncovered])


def test_self_service_portion_approved_false_when_covered_not_approved(
    mocker: MockerFixture,
) -> None:
    covered = _change_decision(mocker, covered=True)
    assert not is_self_service_portion_approved([covered])


def test_self_service_portion_approved_false_when_covered_held(
    mocker: MockerFixture,
) -> None:
    covered = _change_decision(mocker, covered=True)
    covered.apply_context_decision("ctx", DecisionCommand.APPROVED)
    covered.apply_context_decision("ctx", DecisionCommand.HOLD)
    assert not is_self_service_portion_approved([covered])
