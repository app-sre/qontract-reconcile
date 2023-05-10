import pytest

from reconcile.change_owners.change_types import (
    Approver,
    ChangeTypeContext,
)
from reconcile.change_owners.decision import (
    Decision,
    DecisionCommand,
    apply_decisions_to_changes,
    get_approver_decisions_from_mr_comments,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import (
    build_bundle_datafile_change,
    change_type_to_processor,
)

#
# test MR decision comment parsing
#


def test_get_approver_decisions_from_mr_comments() -> None:
    comments = [
        {
            "username": "user-1",
            "body": ("nice\n" f"{DecisionCommand.APPROVED.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-2",
            "body": (f"{DecisionCommand.HOLD.value}\n" "oh wait... big problems"),
            "created_at": "2020-01-03T00:00:00Z",
        },
        {
            "username": "user-2",
            "body": (f"{DecisionCommand.CANCEL_HOLD.value}\n" "never mind... all good"),
            "created_at": "2020-01-04T00:00:00Z",
        },
        {
            "username": "user-1",
            "body": (f"{DecisionCommand.CANCEL_APPROVED.value}"),
            "created_at": "2020-01-05T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == [
        Decision(approver_name="user-1", command=DecisionCommand.APPROVED),
        Decision(approver_name="user-2", command=DecisionCommand.HOLD),
        Decision(approver_name="user-2", command=DecisionCommand.CANCEL_HOLD),
        Decision(approver_name="user-1", command=DecisionCommand.CANCEL_APPROVED),
    ]


def test_get_approver_decisions_from_mr_comments_unordered() -> None:
    comments = [
        {
            "username": "user-1",
            "body": ("nice\n" f"{DecisionCommand.APPROVED.value}"),
            "created_at": "2020-01-02T00:00:00Z",  # this date is later then the next comment
        },
        {
            "username": "user-2",
            "body": (f"{DecisionCommand.HOLD.value}\n" "oh wait... big problems"),
            "created_at": "2020-01-01T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == [
        Decision(approver_name="user-2", command=DecisionCommand.HOLD),
        Decision(approver_name="user-1", command=DecisionCommand.APPROVED),
    ]


def test_approval_comments_none_body() -> None:
    comments = [
        {
            "username": "user-1",
            "body": None,
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert not get_approver_decisions_from_mr_comments(comments)


def test_approver_decision_leading_trailing_spaces() -> None:
    comments = [
        {
            "username": "user-1",
            "body": ("nice\n" f" {DecisionCommand.APPROVED.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-2",
            "body": (f"{DecisionCommand.HOLD.value} \n" "oh wait... big problems"),
            "created_at": "2020-01-02T00:00:00Z",
        },
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


def test_change_decision_auto_approve_only_approver(
    saas_file_changetype: ChangeTypeV1,
) -> None:
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
                Approver(org_username=bot_user, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={},
        changes=[change],
        auto_approver_usernames={bot_user},
    )

    assert change_decision[0].is_approved()


def test_change_decision_auto_approve_not_only_approver(
    saas_file_changetype: ChangeTypeV1,
) -> None:
    nothing_sayer = "nothing-sayer"
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
                Approver(org_username=nothing_sayer, tag_on_merge_requests=False),
                Approver(org_username=bot_user, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={},
        changes=[change],
        auto_approver_usernames={bot_user},
    )

    assert not change_decision[0].is_approved()


def test_change_decision_auto_approve_with_approval(
    saas_file_changetype: ChangeTypeV1,
) -> None:
    nothing_sayer = "nothing-sayer"
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
                Approver(org_username=nothing_sayer, tag_on_merge_requests=False),
                Approver(org_username=bot_user, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions=[
            Decision(approver_name=bot_user, command=DecisionCommand.APPROVED),
        ],
        changes=[change],
        auto_approver_usernames={bot_user},
    )

    assert change_decision[0].is_approved()
