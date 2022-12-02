import pytest

from reconcile.change_owners.change_types import (
    Approver,
    BundleFileType,
    ChangeTypeContext,
    build_change_type_processor,
    create_bundle_file_change,
)
from reconcile.change_owners.decision import (
    Decision,
    DecisionCommand,
    apply_decisions_to_changes,
    get_approver_decisions_from_mr_comments,
)
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1

pytest_plugins = [
    "reconcile.test.change_owners.fixtures",
]

#
# test MR decision comment parsing
#


def test_approver_decision_approve_and_hold():
    comments = [
        {
            "username": "user-1",
            "body": ("nice\n" f"{DecisionCommand.APPROVED.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-2",
            "body": (f"{DecisionCommand.HOLD.value}\n" "oh wait... big problems"),
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=True, hold=False),
        "user-2": Decision(approve=False, hold=True),
    }


def test_approver_approve_and_cancel():
    comments = [
        {
            "username": "user-1",
            "body": ("nice\n" f"{DecisionCommand.APPROVED.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-1",
            "body": (
                f"{DecisionCommand.CANCEL_APPROVED.value}\n"
                "oh wait... changed my mind"
            ),
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=False, hold=False),
    }


def test_approver_hold_and_unhold():
    comments = [
        {
            "username": "user-1",
            "body": ("wait...\n" f"{DecisionCommand.HOLD.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
        {
            "username": "user-1",
            "body": (
                f"{DecisionCommand.CANCEL_HOLD.value}\n" "oh never mind... keep going"
            ),
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=False, hold=False),
    }


def test_unordered_approval_comments():
    comments = [
        {
            "username": "user-1",
            "body": (
                f"{DecisionCommand.CANCEL_HOLD.value}\n" "oh never mind... keep going"
            ),
            "created_at": "2020-01-02T00:00:00Z",
        },
        {
            "username": "user-1",
            "body": ("wait...\n" f"{DecisionCommand.HOLD.value}"),
            "created_at": "2020-01-01T00:00:00Z",
        },
    ]
    assert get_approver_decisions_from_mr_comments(comments) == {
        "user-1": Decision(approve=False, hold=False),
    }


def test_approval_comments_none_body():
    comments = [
        {
            "username": "user-1",
            "body": None,
            "created_at": "2020-01-02T00:00:00Z",
        },
    ]
    assert not get_approver_decisions_from_mr_comments(comments)


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
):
    saas_file_changetype.disabled = disable_change_type

    yea_user = "yea-sayer"
    nay_sayer = "nay-sayer"
    bot_user = "i-am-a-bot"
    change = create_bundle_file_change(
        file_type=BundleFileType.DATAFILE,
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_file_content={"foo": "bar"},
        new_file_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=build_change_type_processor(saas_file_changetype),
            context="something-something",
            approvers=[
                Approver(org_username=yea_user, tag_on_merge_requests=False),
                Approver(org_username=nay_sayer, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={
            yea_user: Decision(approve=True, hold=False),
            nay_sayer: Decision(approve=False, hold=True),
        },
        changes=[change],
        auto_approver_bot_username=bot_user,
    )

    assert change_decision[0].decision.approve == expected_approve
    assert change_decision[0].decision.hold == expected_hold
    assert change_decision[0].diff == change.diff_coverage[0].diff
    assert change_decision[0].file == change.fileref


def test_change_decision_auto_approve_only_approver(saas_file_changetype: ChangeTypeV1):
    bot_user = "i-am-a-bot"
    change = create_bundle_file_change(
        file_type=BundleFileType.DATAFILE,
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_file_content={"foo": "bar"},
        new_file_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=build_change_type_processor(saas_file_changetype),
            context="something-something",
            approvers=[
                Approver(org_username=bot_user, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={},
        changes=[change],
        auto_approver_bot_username=bot_user,
    )

    assert change_decision[0].decision.approve is True


def test_change_decision_auto_approve_not_only_approver(
    saas_file_changetype: ChangeTypeV1,
):
    nothing_sayer = "nothing-sayer"
    bot_user = "i-am-a-bot"
    change = create_bundle_file_change(
        file_type=BundleFileType.DATAFILE,
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_file_content={"foo": "bar"},
        new_file_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=build_change_type_processor(saas_file_changetype),
            context="something-something",
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
        auto_approver_bot_username=bot_user,
    )

    assert change_decision[0].decision.approve is False


def test_change_decision_auto_approve_with_approval(
    saas_file_changetype: ChangeTypeV1,
):
    nothing_sayer = "nothing-sayer"
    bot_user = "i-am-a-bot"
    change = create_bundle_file_change(
        file_type=BundleFileType.DATAFILE,
        path="/my/file.yml",
        schema="/my/schema.yml",
        old_file_content={"foo": "bar"},
        new_file_content={"foo": "baz"},
    )
    assert change and len(change.diff_coverage) == 1
    change.diff_coverage[0].coverage = [
        ChangeTypeContext(
            change_type_processor=build_change_type_processor(saas_file_changetype),
            context="something-something",
            approvers=[
                Approver(org_username=nothing_sayer, tag_on_merge_requests=False),
                Approver(org_username=bot_user, tag_on_merge_requests=False),
            ],
            context_file=change.fileref,
        )
    ]

    change_decision = apply_decisions_to_changes(
        approver_decisions={
            bot_user: Decision(approve=True, hold=False),
        },
        changes=[change],
        auto_approver_bot_username=bot_user,
    )

    assert change_decision[0].decision.approve is True
