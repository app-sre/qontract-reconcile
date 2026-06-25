from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.change_owners.decision import (
    Decision,
    DecisionCommand,
    apply_decisions_to_changes,
    get_approver_decisions_from_mr_comments,
)
from reconcile.test.change_owners.fixtures import (
    build_bundle_datafile_change,
    change_type_to_processor,
)
from reconcile.utils.gitlab_api import Comment

if TYPE_CHECKING:
    from reconcile.change_owners.changes import BundleFileChange
    from reconcile.gql_definitions.change_owners.queries.change_types import (
        ChangeTypeV1,
    )

#
# test MR decision comment parsing
#


def test_get_approver_decisions_from_mr_comments() -> None:
    comments = [
        Comment(
            username="user-1",
            body=f"nice\n{DecisionCommand.APPROVED.value}",
            created_at="2020-01-01T00:00:00Z",
            id=1,
        ),
        Comment(
            username="user-2",
            body=f"{DecisionCommand.HOLD.value}\noh wait... big problems",
            created_at="2020-01-03T00:00:00Z",
            id=2,
        ),
        Comment(
            username="user-2",
            body=f"{DecisionCommand.CANCEL_HOLD.value}\nnever mind... all good",
            created_at="2020-01-04T00:00:00Z",
            id=3,
        ),
        Comment(
            username="user-1",
            body=f"{DecisionCommand.CANCEL_APPROVED.value}",
            created_at="2020-01-05T00:00:00Z",
            id=4,
        ),
    ]
    assert get_approver_decisions_from_mr_comments(comments) == [
        Decision(approver_name="user-1", command=DecisionCommand.APPROVED),
        Decision(approver_name="user-2", command=DecisionCommand.HOLD),
        Decision(approver_name="user-2", command=DecisionCommand.CANCEL_HOLD),
        Decision(approver_name="user-1", command=DecisionCommand.CANCEL_APPROVED),
    ]


def test_get_approver_decisions_from_mr_comments_unordered() -> None:
    comments = [
        Comment(
            username="user-1",
            body=f"nice\n{DecisionCommand.APPROVED.value}",
            created_at="2020-01-02T00:00:00Z",  # this date is later then the next comment
            id=1,
        ),
        Comment(
            username="user-2",
            body=f"{DecisionCommand.HOLD.value}\noh wait... big problems",
            created_at="2020-01-01T00:00:00Z",
            id=2,
        ),
    ]
    assert get_approver_decisions_from_mr_comments(comments) == [
        Decision(approver_name="user-2", command=DecisionCommand.HOLD),
        Decision(approver_name="user-1", command=DecisionCommand.APPROVED),
    ]


def test_approval_comments_empty_body() -> None:
    comments = [
        Comment(
            username="user-1",
            body="",
            created_at="2020-01-02T00:00:00Z",
            id=1,
        ),
    ]
    assert not get_approver_decisions_from_mr_comments(comments)


def test_approver_decision_leading_trailing_spaces() -> None:
    comments = [
        Comment(
            username="user-1",
            body=f"nice\n {DecisionCommand.APPROVED.value}",
            created_at="2020-01-01T00:00:00Z",
            id=1,
        ),
        Comment(
            username="user-2",
            body=f"{DecisionCommand.HOLD.value} \noh wait... big problems",
            created_at="2020-01-02T00:00:00Z",
            id=2,
        ),
    ]
    assert get_approver_decisions_from_mr_comments(comments) == [
        Decision(approver_name="user-1", command=DecisionCommand.APPROVED),
        Decision(approver_name="user-2", command=DecisionCommand.HOLD),
    ]


#
# test decide on changes
#


@pytest.mark.parametrize(
    "disable_change_type,expected_approve,expected_hold",
    [
        (True, False, False),
        (False, True, True),
    ],
)
def test_change_decision(
    saas_file_changetype: ChangeTypeV1,
    disable_change_type: bool,
    expected_approve: bool,
    expected_hold: bool,
) -> None:
    saas_file_changetype.disabled = disable_change_type

    yea_user = "yea-sayer"
    nay_sayer = "nay-sayer"
    bot_user = "i-am-a-bot"
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar"},
        new_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="something-something",
            origin="",
            approvers=[
                Approver(org_username=yea_user, tag_on_merge_requests=False),
                Approver(org_username=nay_sayer, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=yea_user, command=DecisionCommand.APPROVED),
            Decision(approver_name=nay_sayer, command=DecisionCommand.HOLD),
        ],
        changes=[change],
        auto_approver_usernames={bot_user},
    )

    assert change_decision[0].is_approved() == expected_approve
    assert change_decision[0].is_held() == expected_hold
    assert change_decision[0].diff == change.diff_coverage[0].diff
    assert change_decision[0].file == change.fileref


GROUP_A_USER_1 = "group-a-user-1"
GROUP_A_USER_2 = "group-a-user-2"
GROUP_B_USER_1 = "group-b-user-1"
GROUP_B_USER_2 = "group-b-user-2"
GROUP_AB_USER = "group-a-and-b-user"


@pytest.mark.parametrize(
    "decisions,expected_approve,expected_hold",
    [
        # group A holds, group A cancels hold - not on hold anymore
        (
            [
                Decision(GROUP_A_USER_1, DecisionCommand.HOLD),
                Decision(GROUP_A_USER_2, DecisionCommand.CANCEL_HOLD),
            ],
            False,
            False,
        ),
        # group A holds, group B cancels hold - still hold because group A would need to cancel the hold
        (
            [
                Decision(GROUP_A_USER_1, DecisionCommand.HOLD),
                Decision(GROUP_B_USER_1, DecisionCommand.CANCEL_HOLD),
            ],
            False,
            True,
        ),
        # group A approves, group A cancels approval - not approved anymore
        (
            [
                Decision(GROUP_A_USER_1, DecisionCommand.APPROVED),
                Decision(GROUP_A_USER_2, DecisionCommand.CANCEL_APPROVED),
            ],
            False,
            False,
        ),
        # group A approves, group B cancels approval - still approved because group A would need to cancel the approval
        (
            [
                Decision(GROUP_A_USER_1, DecisionCommand.APPROVED),
                Decision(GROUP_B_USER_1, DecisionCommand.CANCEL_APPROVED),
            ],
            True,
            False,
        ),
        # group A approves, user from group A and B cancels approval - not approved anymore
        (
            [
                Decision(GROUP_A_USER_1, DecisionCommand.APPROVED),
                Decision(GROUP_AB_USER, DecisionCommand.CANCEL_APPROVED),
            ],
            False,
            False,
        ),
    ],
)
def test_change_decision_one_change_multiple_groups(
    saas_file_changetype: ChangeTypeV1,
    decisions: list[Decision],
    expected_approve: bool,
    expected_hold: bool,
) -> None:
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar"},
        new_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="team-a-context",
            origin="",
            approvers=[
                Approver(org_username=GROUP_A_USER_1, tag_on_merge_requests=False),
                Approver(org_username=GROUP_A_USER_2, tag_on_merge_requests=False),
                Approver(org_username=GROUP_AB_USER, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        ),
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="team-b-context",
            origin="",
            approvers=[
                Approver(org_username=GROUP_B_USER_1, tag_on_merge_requests=False),
                Approver(org_username=GROUP_B_USER_2, tag_on_merge_requests=False),
                Approver(org_username=GROUP_AB_USER, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        ),
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions=decisions,
        changes=[change],
        auto_approver_usernames=set(),
    )

    assert change_decision[0].is_approved() == expected_approve
    assert change_decision[0].is_held() == expected_hold
    assert change_decision[0].diff == change.diff_coverage[0].diff
    assert change_decision[0].file == change.fileref


def test_change_decision_auto_approve_exclusive_approver_in_role_in_all_diffs_and_contexts(
    saas_file_changetype: ChangeTypeV1,
) -> None:
    """
    Test case: multiple diffs in a changed file, each diff having multiple approver contexts
    where only the auto-approved user is approver in all contexts.

    Test that the change is auto-approved because the only approver for all diffs is an auto-approver
    and there can't be any contradicting decisions from anyone else.
    """
    bot_user = "i-am-a-bot"
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar"},
        new_content={"foo": "baz", "sna": "fu"},
    )
    assert change and len(change.diff_coverage) == 2
    for dc in change.diff_coverage:
        dc.coverage = [
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(saas_file_changetype),
                context="RoleV1 - a role",
                origin="",
                approvers=[
                    Approver(org_username=bot_user, tag_on_merge_requests=False),
                ],
                context_file=change.fileref,
            ),
            ChangeTypeContext(
                change_type_processor=change_type_to_processor(saas_file_changetype),
                context="RoleV1 - another role",
                origin="",
                approvers=[
                    Approver(org_username=bot_user, tag_on_merge_requests=False),
                ],
                context_file=change.fileref,
            ),
        ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={},
        changes=[change],
        auto_approver_usernames={bot_user},
    )

    assert change_decision[0].is_approved()
    assert change_decision[1].is_approved()


def test_change_decision_auto_approve_not_exclusive_approver_in_all_contexts(
    saas_file_changetype: ChangeTypeV1,
) -> None:
    """
    Test case: multiple diffs in a changed file, each diff having multiple approver contexts.
    The auto-approver is the only approver in some of them but not all.

    Test that the change is not auto-approved because the only auto-approver is not the only
    approver in all diffs and all related approver contexts.
    """
    auto_approver_user = "auto-approver"
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar"},
        new_content={"foo": "baz", "sna": "fu"},
    )
    assert change and len(change.diff_coverage) == 2
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="RoleV1 - role 1",
            origin="",
            approvers=[
                Approver(org_username=auto_approver_user, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]
    change.diff_coverage[1].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="RoleV1 - role 2",
            origin="",
            approvers=[
                Approver(org_username=auto_approver_user, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        ),
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="RoleV1 - role 3",
            origin="",
            approvers=[
                Approver(org_username=auto_approver_user, tag_on_merge_requests=False),
                Approver(org_username="another-user", tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        ),
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={},
        changes=[change],
        auto_approver_usernames={auto_approver_user},
    )

    assert change_decision[0].is_approved()
    assert not change_decision[1].is_approved()


def test_change_decision_auto_approver_hold_decision(
    saas_file_changetype: ChangeTypeV1,
) -> None:
    """
    Ensure that an auto-approvers hold decision is honored even when a change
    would be auto-approved otherwise.
    """
    auto_approver = "auto-approver"
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar"},
        new_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="RoleV1 - a role",
            origin="",
            approvers=[
                Approver(org_username=auto_approver, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=auto_approver, command=DecisionCommand.HOLD),
        ],
        changes=[change],
        auto_approver_usernames={auto_approver},
    )

    assert not change_decision[0].is_approved()
    assert change_decision[0].is_held()


#
# test MR author hold decisions
#

MR_AUTHOR = "mr-author"
APPROVER_USER = "approver-user"


@pytest.fixture
def change_with_coverage(
    saas_file_changetype: ChangeTypeV1,
) -> BundleFileChange:
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar"},
        new_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="team-context",
            origin="",
            approvers=[
                Approver(org_username=APPROVER_USER, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]
    return change


def test_mr_author_hold_as_non_approver(
    change_with_coverage: BundleFileChange,
) -> None:
    """
    The MR author can /hold their own MR even when not in any approver group.
    """
    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.HOLD),
        ],
        changes=[change_with_coverage],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )

    assert change_decision[0].is_held()


def test_non_author_non_approver_hold_ignored(
    change_with_coverage: BundleFileChange,
) -> None:
    """
    A user who is neither the MR author nor an approver cannot hold the MR.
    """
    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name="random-user", command=DecisionCommand.HOLD),
        ],
        changes=[change_with_coverage],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )

    assert not change_decision[0].is_held()


def test_mr_author_hold_cancel(
    change_with_coverage: BundleFileChange,
) -> None:
    """
    The MR author can /hold cancel their own hold.
    """
    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.HOLD),
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.CANCEL_HOLD),
        ],
        changes=[change_with_coverage],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )

    assert not change_decision[0].is_held()


def test_mr_author_hold_coexists_with_approval(
    change_with_coverage: BundleFileChange,
) -> None:
    """
    An approver /lgtm and the MR author (non-approver) /hold should result in
    the change being both approved and held.
    """
    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=APPROVER_USER, command=DecisionCommand.APPROVED),
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.HOLD),
        ],
        changes=[change_with_coverage],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )

    assert change_decision[0].is_approved()
    assert change_decision[0].is_held()


def test_mr_author_hold_as_approver_uses_normal_context(
    saas_file_changetype: ChangeTypeV1,
) -> None:
    """
    When the MR author is already a change owner, /hold is applied through the
    normal approver path (context = the change-type context) and NOT through
    the special "mr-author" context.
    """
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar"},
        new_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="team-context",
            origin="",
            approvers=[
                Approver(org_username=MR_AUTHOR, tag_on_merge_requests=False),
                Approver(org_username=APPROVER_USER, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.HOLD),
        ],
        changes=[change],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )

    assert change_decision[0].is_held()
    assert "team-context" in change_decision[0].hold
    assert "mr-author" not in change_decision[0].hold


def test_mr_author_hold_mixed_mr_approver_on_one_diff(
    saas_file_changetype: ChangeTypeV1,
) -> None:
    """
    Mixed MR: the author is an approver on diff 0 but not on diff 1.
    /hold applies via the normal approver path on diff 0 and via the
    "mr-author" context on diff 1.  The author can /hold cancel to
    remove both — no stuck state.
    """
    other_approver = "other-approver"
    change = build_bundle_datafile_change(
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_content={"foo": "bar", "baz": "qux"},
        new_content={"foo": "changed", "baz": "also-changed"},
    )
    assert change and len(change.diff_coverage) == 2

    # diff 0: author IS an approver
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="author-team",
            origin="",
            approvers=[
                Approver(org_username=MR_AUTHOR, tag_on_merge_requests=False),
                Approver(org_username=APPROVER_USER, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]
    # diff 1: author is NOT an approver
    change.diff_coverage[1].coverage = [
        ChangeTypeContext(
            change_type_processor=change_type_to_processor(saas_file_changetype),
            context="other-team",
            origin="",
            approvers=[
                Approver(org_username=other_approver, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    # both diffs are held after /hold
    hold_decisions = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.HOLD),
        ],
        changes=[change],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )
    assert hold_decisions[0].is_held()
    assert "author-team" in hold_decisions[0].hold
    assert hold_decisions[1].is_held()
    assert "mr-author" in hold_decisions[1].hold

    # author can /hold cancel to remove both — no stuck state
    cancel_decisions = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.HOLD),
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.CANCEL_HOLD),
        ],
        changes=[change],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )
    assert not cancel_decisions[0].is_held()
    assert not cancel_decisions[1].is_held()


def test_change_owner_can_unhold_author_hold(
    change_with_coverage: BundleFileChange,
) -> None:
    """
    A change owner can /hold cancel an MR that was held by the author.
    """
    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=MR_AUTHOR, command=DecisionCommand.HOLD),
            Decision(approver_name=APPROVER_USER, command=DecisionCommand.CANCEL_HOLD),
        ],
        changes=[change_with_coverage],
        auto_approver_usernames=set(),
        mr_author=MR_AUTHOR,
    )

    assert not change_decision[0].is_held()
