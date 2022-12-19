from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any

from reconcile.change_owners.bundle import FileRef
from reconcile.change_owners.change_types import (
    BundleFileChange,
    ChangeTypeContext,
)
from reconcile.change_owners.diff import Diff


@dataclass
class Decision:

    approve: bool = False
    hold: bool = False


class DecisionCommand(Enum):
    APPROVED = "/lgtm"
    CANCEL_APPROVED = "/lgtm cancel"
    HOLD = "/hold"
    CANCEL_HOLD = "/hold cancel"


def get_approver_decisions_from_mr_comments(
    comments: list[dict[str, Any]]
) -> dict[str, Decision]:
    decisions_by_users: dict[str, Decision] = defaultdict(Decision)
    for c in sorted(comments, key=lambda k: k["created_at"]):
        commenter = c["username"]
        comment_body = c.get("body")
        for line in comment_body.split("\n") if comment_body else []:
            if line == DecisionCommand.APPROVED.value:
                decisions_by_users[commenter].approve = True
            if line == DecisionCommand.CANCEL_APPROVED.value:
                decisions_by_users[commenter].approve = False
            if line == DecisionCommand.HOLD.value:
                decisions_by_users[commenter].hold = True
            if line == DecisionCommand.CANCEL_HOLD.value:
                decisions_by_users[commenter].hold = False
    return decisions_by_users


@dataclass
class ChangeDecision:

    file: FileRef
    diff: Diff
    coverage: list[ChangeTypeContext]
    decision: Decision


def apply_decisions_to_changes(
    changes: list[BundleFileChange],
    approver_decisions: dict[str, Decision],
    auto_approver_bot_username: str,
) -> list[ChangeDecision]:
    """
    Apply and aggregate approver decisions to changes. Each diff of a
    BundleFileChange is mapped to a ChangeDecisions that carries the
    decisions of their respective approvers. This datastructure is used
    to generate the coverage report and to reason about the approval
    state of the MR.
    """
    diff_decisions = []
    for c in changes:
        for d in c.diff_coverage:
            change_decision = ChangeDecision(
                file=c.fileref, diff=d.diff, coverage=d.coverage, decision=Decision()
            )
            diff_decisions.append(change_decision)
            for change_type_context in change_decision.coverage:
                if change_type_context.disabled:
                    # approvers of a disabled change-type are ignored
                    continue
                if (
                    len(change_type_context.approvers) == 1
                    and change_type_context.approvers[0].org_username
                    == auto_approver_bot_username
                ):
                    change_decision.decision.approve |= True
                    continue
                for approver in change_type_context.approvers:
                    if approver.org_username in approver_decisions:
                        if approver_decisions[approver.org_username].approve:
                            change_decision.decision.approve |= True
                        if approver_decisions[approver.org_username].hold:
                            change_decision.decision.hold |= True
    return diff_decisions
