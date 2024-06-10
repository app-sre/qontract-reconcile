from collections import Counter

from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    AWSAccountV1,
)


def validate(account: AWSAccountV1) -> bool:
    """Validate the account configurations."""
    # check referenced quotas don't overlap
    quotas = Counter([
        (quota.service_code, quota.quota_code)
        for quota_limit in account.quota_limits or []
        for quota in quota_limit.quotas or []
    ])
    errors = [
        ValueError(
            f"Quota service_code={service_code}, quota_code={quota_code} is referenced multiple times in account {account.name}"
        )
        for (service_code, quota_code), cnt in quotas.items()
        if cnt > 1
    ]
    if errors:
        raise ExceptionGroup("Multiple quotas are referenced in the account", errors)

    if account.organization_accounts or account.account_requests:
        # it's payer account
        if not account.premium_support:
            raise ValueError(
                f"Premium support is required for payer account {account.name}"
            )

    # security contact is mandatory for all accounts since June 2024
    if not account.security_contact:
        raise ValueError(f"Security contact is required for account {account.name}")
    return True


def state_key(account: str, task: str) -> str:
    """Compute a state key based on the organization account and the task name."""
    return f"task.{account}.{task}"
