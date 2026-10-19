from __future__ import annotations

from typing import TYPE_CHECKING, cast

import jsonpath_ng
import pytest

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.bundle import BundleFileType, FileRef
from reconcile.change_owners.change_owners import (
    build_change_summary,
    build_status_message,
    is_change_admitted,
    is_self_service_portion_approved,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    DiffCoverage,
)
from reconcile.change_owners.decision import ChangeDecision, DecisionCommand
from reconcile.change_owners.diff import Diff, DiffType
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


def _change_decision(
    mocker: MockerFixture, *, approvers: list[str] | None = None
) -> ChangeDecision:
    """approvers=None means uncovered; otherwise a single covering context
    with the given approver usernames."""
    coverage = (
        [
            ChangeTypeContext(
                change_type_processor=mocker.patch(
                    "reconcile.change_owners.change_types.ChangeTypeProcessor"
                ),
                context="ctx",
                origin="",
                context_file=FileRef(
                    file_type=BundleFileType.DATAFILE, path="/x.yml", schema=None
                ),
                approvers=[Approver(org_username=u) for u in approvers],
            )
        ]
        if approvers is not None
        else []
    )
    return ChangeDecision(
        file=mocker.patch("reconcile.change_owners.bundle.FileRef"),
        diff=mocker.patch("reconcile.change_owners.diff.Diff"),
        coverage=coverage,
    )


def test_self_service_portion_approved_no_covered_changes(
    mocker: MockerFixture,
) -> None:
    """an MR with only non-self-serviceable changes is vacuously approved here"""
    uncovered = _change_decision(mocker)
    assert is_self_service_portion_approved([uncovered], set())


def test_self_service_portion_approved_ignores_uncovered_changes(
    mocker: MockerFixture,
) -> None:
    """the non-self-serviceable part of the MR must not block this check"""
    covered = _change_decision(mocker, approvers=["alice"])
    covered.apply_context_decision("ctx", DecisionCommand.APPROVED)
    uncovered = _change_decision(mocker)
    assert is_self_service_portion_approved([covered, uncovered], set())


def test_self_service_portion_approved_false_when_covered_not_approved(
    mocker: MockerFixture,
) -> None:
    covered = _change_decision(mocker, approvers=["alice"])
    assert not is_self_service_portion_approved([covered], set())


def test_self_service_portion_approved_false_when_covered_held(
    mocker: MockerFixture,
) -> None:
    covered = _change_decision(mocker, approvers=["alice"])
    covered.apply_context_decision("ctx", DecisionCommand.APPROVED)
    covered.apply_context_decision("ctx", DecisionCommand.HOLD)
    assert not is_self_service_portion_approved([covered], set())


def test_self_service_portion_approved_ignores_app_sre_only_coverage(
    mocker: MockerFixture,
) -> None:
    """a change whose only possible approver is AppSRE must not block the
    review queue on AppSRE approving it themselves - they can't see it in
    the queue to do so until it's no longer hidden"""
    covered = _change_decision(mocker, approvers=["app-sre-bot"])
    assert is_self_service_portion_approved([covered], {"app-sre-bot"})


def test_self_service_portion_approved_requires_approval_when_tenant_also_approver(
    mocker: MockerFixture,
) -> None:
    """a mixed tenant/AppSRE approver list is still genuinely
    self-serviceable - the tenant can approve it without AppSRE"""
    covered = _change_decision(mocker, approvers=["app-sre-bot", "alice"])
    assert not is_self_service_portion_approved([covered], {"app-sre-bot"})


#
# status message tests
#


def test_status_message_not_admitted_takes_priority() -> None:
    message = build_status_message(
        self_serviceable=True,
        self_service_portion_approved=True,
        authoritative=True,
        change_admitted=False,
        approver_reachability=set(),
        supported_commands=[],
    )
    assert "Approval Required" in message
    assert "/ok-to-test" in message


def test_status_message_self_serviceable() -> None:
    message = build_status_message(
        self_serviceable=True,
        self_service_portion_approved=True,
        authoritative=True,
        change_admitted=True,
        approver_reachability=set(),
        supported_commands=[],
    )
    assert "Ready for Review" in message


def test_status_message_pending_self_service_approval() -> None:
    """not self-serviceable overall, and the self-serviceable part isn't
    approved yet - must not claim AppSRE is already reviewing it"""
    message = build_status_message(
        self_serviceable=False,
        self_service_portion_approved=False,
        authoritative=True,
        change_admitted=True,
        approver_reachability=set(),
        supported_commands=[],
    )
    assert "Self-Service Approval Needed First" in message
    # must not claim AppSRE is already reviewing - it isn't, the MR is
    # hidden from their review queue until the self-service part lands
    assert "AppSRE Review Required" not in message
    assert "will review via" not in message


def test_status_message_appsre_review_required() -> None:
    """not self-serviceable overall, but the self-serviceable part (if any)
    is already approved - genuinely waiting on AppSRE now"""
    message = build_status_message(
        self_serviceable=False,
        self_service_portion_approved=True,
        authoritative=True,
        change_admitted=True,
        approver_reachability=set(),
        supported_commands=[],
    )
    assert "AppSRE Review Required" in message


#
# change summary tests
#


def _decision_for_file(path: str, diff_type: DiffType) -> ChangeDecision:
    return ChangeDecision(
        file=FileRef(file_type=BundleFileType.DATAFILE, path=path, schema=None),
        diff=Diff(path=jsonpath_ng.Root(), diff_type=diff_type, old=None, new=None),
        coverage=[],
    )


def test_change_summary_no_changes() -> None:
    assert build_change_summary([]) == "No changes detected."


def test_change_summary_single_change() -> None:
    summary = build_change_summary([
        _decision_for_file("/a.yml", DiffType.ADDED),
    ])
    assert summary == "* `/a.yml`: 1 addition"


def test_change_summary_groups_by_file_and_counts_types() -> None:
    summary = build_change_summary([
        _decision_for_file("/a.yml", DiffType.ADDED),
        _decision_for_file("/a.yml", DiffType.CHANGED),
        _decision_for_file("/b.yml", DiffType.REMOVED),
        _decision_for_file("/b.yml", DiffType.REMOVED),
    ])
    assert "* `/a.yml`: 1 addition, 1 change" in summary
    assert "* `/b.yml`: 2 removals" in summary
