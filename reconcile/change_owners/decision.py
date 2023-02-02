from collections import defaultdict
from collections.abc import (
    Iterable,
    Mapping,
)
from dataclasses import dataclass
from enum import Enum
from typing import Any

from reconcile.change_owners.bundle import FileRef
from reconcile.change_owners.change_types import (
    BundleFileChange,
    ChangeTypeContext,
)
from reconcile.change_owners.diff import Diff


class DecisionCommand(Enum):
    APPROVED = "/lgtm"
    CANCEL_APPROVED = "/lgtm cancel"
    HOLD = "/hold"
    CANCEL_HOLD = "/hold cancel"


@dataclass
class Decision:

    approver_name: str
    command: DecisionCommand


def get_approver_decisions_from_mr_comments(
    comments: Iterable[Mapping[str, Any]]
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
class ChangeDecision:

    file: FileRef
    diff: Diff
    coverage: list[ChangeTypeContext]

    def __post_init__(self) -> None:
        self.approve: dict[str, bool] = defaultdict(bool)
        self.hold: dict[str, bool] = defaultdict(bool)

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

    def is_approved(self) -> bool:
        return any(self.approve.values())

    def is_held(self) -> bool:
        return any(self.hold.values())

    def deduped_coverage(self) -> list[ChangeTypeContext]:
        unique_coverage = {}
        for ctx in self.coverage:
            key = f"{ctx.change_type_processor.name}:{ctx.context}"
            unique_coverage[key] = ctx
        return list(unique_coverage.values())


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

                # autoapproval authors
                if (
                    len(change_type_context.approvers) == 1
                    and change_type_context.approvers[0].org_username
                    in auto_approver_usernames
                ):
                    change_decision.apply_decision(
                        change_type_context, DecisionCommand.APPROVED
                    )
                    continue

                for decision in approver_decisions:
                    if change_type_context.includes_approver(decision.approver_name):
                        change_decision.apply_decision(
                            change_type_context, decision.command
                        )
    return diff_decisions
