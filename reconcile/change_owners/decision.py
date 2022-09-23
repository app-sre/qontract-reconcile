from dataclasses import dataclass
from collections import defaultdict
from enum import Enum


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
    comments: list[dict[str, str]]
) -> dict[str, Decision]:
    decisions_by_users: dict[str, Decision] = defaultdict(Decision)
    for c in sorted(comments, key=lambda k: k["created_at"]):
        commenter = c["username"]
        for line in c.get("body", "").split("\n"):
            if line == DecisionCommand.APPROVED.value:
                decisions_by_users[commenter].approve = True
            if line == DecisionCommand.CANCEL_APPROVED.value:
                decisions_by_users[commenter].approve = False
            if line == DecisionCommand.HOLD.value:
                decisions_by_users[commenter].hold = True
            if line == DecisionCommand.CANCEL_HOLD.value:
                decisions_by_users[commenter].hold = False
    return decisions_by_users
