import pytest

from reconcile.aws_account_manager.utils import state_key, validate
from reconcile.gql_definitions.aws_account_manager.aws_accounts import AWSAccountV1
from reconcile.gql_definitions.fragments.aws_account_managed import (
    AWSQuotaLimitsV1,
    AWSQuotaV1,
)


def test_aws_account_manager_utils_is_valid_overlapping_quotas(
    non_org_account: AWSAccountV1,
) -> None:
    # be sure the account is valid at the beginning
    assert validate(non_org_account)

    non_org_account.quota_limits = [
        AWSQuotaLimitsV1(
            name="name",
            quotas=[AWSQuotaV1(serviceCode="service", quotaCode="code", value=1.0)],
        ),
        AWSQuotaLimitsV1(
            name="name",
            # overlapping quota
            quotas=[AWSQuotaV1(serviceCode="service", quotaCode="code", value=2.0)],
        ),
    ]
    with pytest.raises(ExceptionGroup):
        validate(non_org_account)


def test_aws_account_manager_utils_is_valid_payer_account_must_have_premium_support(
    payer_account: AWSAccountV1,
) -> None:
    # be sure the account is valid at the beginning
    assert validate(payer_account)

    payer_account.premium_support = False
    with pytest.raises(ValueError):
        validate(payer_account)


def test_aws_account_manager_utils_security_contact_is_set(
    payer_account: AWSAccountV1,
) -> None:
    # be sure the account is valid at the beginning
    assert validate(payer_account)

    payer_account.security_contact = None
    with pytest.raises(ValueError):
        validate(payer_account)


def test_aws_account_manager_utils_state_key() -> None:
    account = "account"
    task = "task"
    assert "task.account.task" == state_key(account, task)
