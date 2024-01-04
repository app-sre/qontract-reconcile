from collections import defaultdict
from collections.abc import (
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Optional,
)

from reconcile.change_owners.approver import (
    Approver,
    ApproverReachability,
)
from reconcile.change_owners.bundle import FileRef
from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.change_owners.changes import BundleFileChange
from reconcile.change_owners.diff import Diff


class DecisionCommand(Enum):
    APPROVED = "/lgtm"
    CANCEL_APPROVED = "/lgtm cancel"
    HOLD = "/hold"
    CANCEL_HOLD = "/hold cancel"
    GOOD_TO_TEST = "/good-to-test"


@dataclass
class Decision:
    approver_name: str
    command: DecisionCommand


def get_approver_decisions_from_mr_comments(
    comments: Iterable[Mapping[str, Any]],
) -> list[Decision]:
    decisions: list[Decision] = []
    for c in sorted(comments, key=lambda k: k["created_at"]):
        commenter = c["username"]
        comment_body = c.get("body")
        for line in comment_body.split("\n") if comment_body else []:
            line = line.strip()
            if line == DecisionCommand.APPROVED.value:
                decisions.append(
                    Decision(approver_name=commenter, command=DecisionCommand.APPROVED)
                )
            if line == DecisionCommand.CANCEL_APPROVED.value:
                decisions.append(
                    Decision(
                        approver_name=commenter, command=DecisionCommand.CANCEL_APPROVED
                    )
                )
            if line == DecisionCommand.HOLD.value:
                decisions.append(
                    Decision(approver_name=commenter, command=DecisionCommand.HOLD)
                )
            if line == DecisionCommand.CANCEL_HOLD.value:
                decisions.append(
                    Decision(
                        approver_name=commenter, command=DecisionCommand.CANCEL_HOLD
                    )
                )
    return decisions


@dataclass
class ChangeResponsibles:
    context: str
    approvers: list[Approver]
    approver_reachability: Optional[list[ApproverReachability]] = None


@dataclass
class ChangeDecision:
    file: FileRef
    diff: Diff
    coverage: list[ChangeTypeContext]

    def __post_init__(self) -> None:
        self.approve: dict[str, bool] = defaultdict(bool)
        self.hold: dict[str, bool] = defaultdict(bool)
        self.context_auto_approval: dict[str, bool] = defaultdict(bool)

    def apply_decision(
        self, ctx: ChangeTypeContext, decision_cmd: DecisionCommand
    ) -> None:
        if decision_cmd == DecisionCommand.APPROVED:
            self.approve[ctx.context] = True
        elif decision_cmd == DecisionCommand.CANCEL_APPROVED:
            self.approve[ctx.context] = False
        elif decision_cmd == DecisionCommand.HOLD:
            self.hold[ctx.context] = True
        elif decision_cmd == DecisionCommand.CANCEL_HOLD:
            self.hold[ctx.context] = False

    def auto_approve(self, ctx: ChangeTypeContext, decision: bool) -> None:
        self.context_auto_approval[ctx.context] = decision

    def is_approved(self) -> bool:
        """
        A diff is considered approved if
        * at least one eligible approver party (context) approved it
          OR
        * ALL eligible approver parties (contexts) have issued an auto-approval

        An approved diff does not imply that the MR is approved. There might still be holds.
        """
        return any(self.approve.values()) or (
            len(self.context_auto_approval) > 0
            and all(self.context_auto_approval.values())
        )

    def is_held(self) -> bool:
        return any(self.hold.values())

    @property
    def change_responsibles(self) -> list[ChangeResponsibles]:
        unique_contexts: dict[str, ChangeResponsibles] = {}
        for ctx in self.coverage:
            if ctx.context in unique_contexts:
                continue
            unique_contexts[ctx.context] = ChangeResponsibles(
                context=ctx.context,
                approvers=ctx.approvers,
                approver_reachability=ctx.approver_reachability,
            )
        return list(unique_contexts.values())


def apply_decisions_to_changes(
    changes: Iterable[BundleFileChange],
    approver_decisions: Iterable[Decision],
    auto_approver_usernames: set[str],
) -> list[ChangeDecision]:
    """
    Apply and aggregate approver decisions to changes. Each diff of a
    BundleFileChange is mapped to a ChangeDecisions that carries the
    decisions of their respective approvers. This datastructure is used
    to generate the coverage report and to reason about the approval
    state of the MR.
    """
    approvers_decisions_by_name = {
        d.approver_name: d.command for d in approver_decisions
    }

    diff_decisions = []
    for c in changes:
        for d in c.diff_coverage:
            change_decision = ChangeDecision(
                file=c.fileref, diff=d.diff, coverage=d.coverage
            )
            diff_decisions.append(change_decision)

            for change_type_context in change_decision.coverage:
                # approvers of a disabled change-type are ignored
                if change_type_context.disabled:
                    continue

                # a context is auto-approved if
                #  * it has only one approver
                #  * the approver is an auto-approver
                #  * the approver has not issued an explicit hold decision
                context_auto_approved = (
                    len(change_type_context.approvers) == 1
                    and change_type_context.approvers[0].org_username
                    in auto_approver_usernames
                    and approvers_decisions_by_name.get(
                        change_type_context.approvers[0].org_username
                    )
                    != DecisionCommand.HOLD
                )
                change_decision.auto_approve(change_type_context, context_auto_approved)

                for decision in approver_decisions:
                    if change_type_context.includes_approver(decision.approver_name):
                        change_decision.apply_decision(
                            change_type_context, decision.command
                        )
    return diff_decisions
