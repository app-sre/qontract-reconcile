import pytest

from reconcile.external_resources.model import (
    ExternalResourceKey,
    Reconciliation,
)
from reconcile.external_resources.reconciler import ReconciliationK8sJob


@pytest.mark.parametrize(
    "is_dry_run, dry_run_suffix, custom_key, expected_prefix_format",
    [
        # Non-dry-run jobs
        (False, "", None, "er-{identifier}"),
        # Dry-run jobs with suffix
        (True, "1234567", None, "er-dry-run-{identifier}-1234567"),
        # Dry-run with long suffix
        (True, "12345678901234567890", None, "er-dry-run-{identifier}-1234567"),
        # Dry-run with empty suffix
        (True, "", None, "er-dry-run-{identifier}-"),
        # Non-dry-run with long identifier
        (
            False,
            "",
            ExternalResourceKey(
                provision_provider="aws",
                provisioner_name="app-sre",
                provider="aws-rds-cluster-very-long-name",
                identifier="my-super-long-identifier-that-exceeds-the-limit-significantly",
            ),
            "er-{identifier}",
        ),
        # Dry-run with long identifier
        (
            True,
            "9999999",
            ExternalResourceKey(
                provision_provider="aws",
                provisioner_name="app-sre",
                provider="aws-rds-cluster-very-long-name",
                identifier="my-super-long-identifier-that-exceeds-the-limit-significantly",
            ),
            "er-dry-run-{identifier}-9999999",
        ),
    ],
)
def test_name_prefix(
    reconciliation: Reconciliation,
    is_dry_run: bool,
    dry_run_suffix: str,
    custom_key: ExternalResourceKey | None,
    expected_prefix_format: str,
) -> None:
    """Test name_prefix for various configurations"""
    # Use custom key if provided, otherwise use the default from fixture
    if custom_key:
        test_reconciliation = Reconciliation(
            key=custom_key,
            resource_hash=reconciliation.resource_hash,
            input=reconciliation.input,
            action=reconciliation.action,
            module_configuration=reconciliation.module_configuration,
        )
    else:
        test_reconciliation = reconciliation

    job = ReconciliationK8sJob(
        reconciliation=test_reconciliation,
        is_dry_run=is_dry_run,
        dry_run_suffix=dry_run_suffix,
    )

    identifier = (
        f"{test_reconciliation.key.provider}-{test_reconciliation.key.identifier}"
    )
    truncated_identifier = identifier[:45] if is_dry_run else identifier[:53]
    expected_prefix = expected_prefix_format.format(identifier=truncated_identifier)
    result = job.name_prefix()

    assert result == expected_prefix


def test_full_job_name_format(reconciliation: Reconciliation) -> None:
    """Test that the full job name includes prefix and digest"""
    job = ReconciliationK8sJob(
        reconciliation=reconciliation,
        is_dry_run=False,
    )

    full_name = job.name()
    prefix = job.name_prefix()

    assert full_name.startswith(prefix)
