from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    AWSAccountV1,
)


def is_valid(account: AWSAccountV1) -> bool:
    """Validate the account configurations."""
    # check referenced quotas don't overlap
    seen_quotas = []
    for quota_limit in account.quota_limits or []:
        for quota in quota_limit.quotas or []:
            if (quota.service_code, quota.quota_code) in seen_quotas:
                raise ValueError(
                    f"Quota {quota.service_code=}, {quota.quota_code=} is referenced multiple times in account {account.name}"
                )
            seen_quotas.append((quota.service_code, quota.quota_code))

    if account.organization_accounts or account.account_requests:
        # it's payer account
        if not account.premium_support:
            raise ValueError(
                f"Premium support is required for payer account {account.name}"
            )

    return True


def state_key(account: str, task: str) -> str:
    """Compute a state key based on the organization account and the task name."""
    return f"task.{account}.{task}"
