APPROVED = "bot/approved"
AUTO_MERGE = "bot/automerge"
AWAITING_APPROVAL = "awaiting-approval"
BLOCKED_BOT_ACCESS = "blocked/bot-access"
CHANGES_REQUESTED = "changes-requested"
DO_NOT_MERGE_HOLD = "do-not-merge/hold"
DO_NOT_MERGE_PENDING_REVIEW = "do-not-merge/pending-review"
HOLD = "bot/hold"
LGTM = "lgtm"
SAAS_FILE_UPDATE = "saas-file-update"
NEEDS_REBASE = "needs-rebase"
SELF_SERVICEABLE = "self-serviceable"
NOT_SELF_SERVICEABLE = "not-self-serviceable"
ONBOARDING = "onboarding"


def prioritized_approval_label(priority: str) -> str:
    return f"{APPROVED}: {priority}"


def change_owner_label(label: str) -> str:
    return f"change-owner/{label}"
